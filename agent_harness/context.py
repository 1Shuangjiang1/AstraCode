"""Context budgeting and loss-aware tool-result compaction.

The durable conversation remains in the session database/event log.  This module
only shapes the transient view sent to the model.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .state import atomic_write


COMPACT_MARKER = "<tool-result-compacted"


def estimate_tokens(value) -> int:
    """Cheap provider-independent estimate used for budgets, never billing."""
    return max(1, len(json.dumps(value, default=str, ensure_ascii=False)) // 4)


@dataclass(frozen=True)
class ContextPolicy:
    input_budget: int = 100_000
    output_reserve: int = 8_000
    keep_recent_tool_results: int = 4
    compact_tool_result_above: int = 1_200
    preview_head: int = 520
    preview_tail: int = 260


@dataclass
class ContextReport:
    message_tokens: int
    system_tokens: int
    tool_schema_tokens: int
    output_reserve: int
    request_tokens: int
    compacted_results: int = 0
    saved_tokens: int = 0
    artifacts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "messageTokens": self.message_tokens,
            "systemTokens": self.system_tokens,
            "toolSchemaTokens": self.tool_schema_tokens,
            "outputReserve": self.output_reserve,
            "requestTokens": self.request_tokens,
            "compactedResults": self.compacted_results,
            "savedTokens": self.saved_tokens,
            "artifacts": list(self.artifacts),
        }


class ContextManager:
    """Build a compact model view while retaining recoverable raw tool output."""

    def __init__(self, artifact_root: Path, policy: ContextPolicy):
        self.artifact_root = artifact_root
        self.policy = policy

    @staticmethod
    def _block_value(block, key: str, default=None):
        if isinstance(block, dict):
            return block.get(key, default)
        return getattr(block, key, default)

    def _tool_calls(self, messages: list) -> dict[str, tuple[str, dict]]:
        calls: dict[str, tuple[str, dict]] = {}
        for message in messages:
            if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
                continue
            for block in message["content"]:
                if self._block_value(block, "type") == "tool_use":
                    calls[str(self._block_value(block, "id", ""))] = (
                        str(self._block_value(block, "name", "unknown")),
                        self._block_value(block, "input", {}) or {},
                    )
        return calls

    @staticmethod
    def _result_parts(messages: list) -> list[dict]:
        parts: list[dict] = []
        for message in messages:
            if message.get("role") == "user" and isinstance(message.get("content"), list):
                parts.extend(
                    part for part in message["content"]
                    if isinstance(part, dict) and part.get("type") == "tool_result"
                )
        return parts

    def _store_raw_result(self, tool_name: str, tool_id: str, content: str) -> tuple[Path, str]:
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        safe_tool = "".join(char if char.isalnum() or char in "-_" else "_" for char in tool_name)[:32]
        directory = self.artifact_root / "tool-results"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{int(time.time())}_{safe_tool}_{tool_id[:12]}_{digest[:10]}.txt"
        if not path.exists():
            atomic_write(path, content)
        return path, digest

    def compact_tool_results(self, messages: list) -> dict:
        """Compact old, large outputs in place and keep raw output in an artifact."""
        calls = self._tool_calls(messages)
        results = self._result_parts(messages)
        candidates = results[:-self.policy.keep_recent_tool_results]
        saved_tokens = 0
        artifacts: list[str] = []
        compacted = 0
        for part in candidates:
            content = part.get("content")
            if not isinstance(content, str) or len(content) <= self.policy.compact_tool_result_above:
                continue
            if content.lstrip().startswith(COMPACT_MARKER):
                continue
            tool_id = str(part.get("tool_use_id", "unknown"))
            tool_name, tool_input = calls.get(tool_id, ("unknown", {}))
            path, digest = self._store_raw_result(tool_name, tool_id, content)
            status = "error" if content.lower().startswith(("error", "permission denied")) else "ok"
            input_text = json.dumps(tool_input, ensure_ascii=False, default=str)
            if len(input_text) > 420:
                input_text = input_text[:417] + "..."
            head = content[:self.policy.preview_head]
            tail = content[-self.policy.preview_tail:] if len(content) > self.policy.preview_head else ""
            preview = head + ("\n… [middle omitted] …\n" + tail if tail else "")
            replacement = (
                f'<tool-result-compacted tool="{tool_name}" status="{status}" '
                f'chars="{len(content)}" sha256="{digest[:16]}" '
                f'artifact="{path}">\n'
                f"input: {input_text}\npreview:\n{preview}\n"
                "</tool-result-compacted>"
            )
            saved_tokens += max(0, estimate_tokens(content) - estimate_tokens(replacement))
            part["content"] = replacement
            compacted += 1
            artifacts.append(str(path))
        return {"compactedResults": compacted, "savedTokens": saved_tokens, "artifacts": artifacts}

    def measure(self, system: str, messages: list, tools: list) -> ContextReport:
        message_tokens = estimate_tokens(messages)
        system_tokens = estimate_tokens(system)
        tool_schema_tokens = estimate_tokens(tools)
        request_tokens = message_tokens + system_tokens + tool_schema_tokens + self.policy.output_reserve
        return ContextReport(
            message_tokens=message_tokens,
            system_tokens=system_tokens,
            tool_schema_tokens=tool_schema_tokens,
            output_reserve=self.policy.output_reserve,
            request_tokens=request_tokens,
        )

    def prepare(self, system: str, messages: list, tools: list) -> tuple[ContextReport, bool]:
        compact = self.compact_tool_results(messages)
        report = self.measure(system, messages, tools)
        report.compacted_results = compact["compactedResults"]
        report.saved_tokens = compact["savedTokens"]
        report.artifacts = compact["artifacts"]
        return report, report.request_tokens >= self.policy.input_budget
