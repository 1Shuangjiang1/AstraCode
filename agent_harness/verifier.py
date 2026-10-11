"""Independent, read-only verification after the implementation agent stops.

The completion gate answers "did the agent produce the minimum required tool
evidence?".  This module answers the separate question "does the resulting
workspace appear to satisfy the user's request?" without trusting the lead
agent's final prose.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .ui import text_content


VALID_VERIFICATION_MODES = {"off", "standard", "strict"}
READ_ONLY_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the active workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories in the active workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    },
    {
        "name": "path_exists",
        "description": "Check whether a workspace path exists.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]


@dataclass
class VerificationResult:
    mode: str
    verdict: str
    summary: str
    confidence: float = 0.0
    checks: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    duration_ms: int = 0
    raw_text: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "verdict": self.verdict, "passed": self.passed,
            "summary": self.summary, "confidence": self.confidence,
            "checks": self.checks, "issues": self.issues, "rounds": self.rounds,
            "duration_ms": self.duration_ms,
        }


class Verifier:
    """Use a fresh model context and only read-only tools to verify a run."""

    def __init__(self, client, model: str, max_tokens: int = 6000,
                 trace_callback: Callable[[dict[str, Any]], None] | None = None):
        self.client = client
        self.model = model
        self.max_tokens = max(1200, min(int(max_tokens), 8000))
        self.trace_callback = trace_callback

    def _trace(self, event_type: str, **payload: Any) -> None:
        if self.trace_callback:
            self.trace_callback({"type": event_type, **payload})

    @staticmethod
    def _value(block: Any, key: str, default: Any = None) -> Any:
        return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)

    @staticmethod
    def _parse(text: str, mode: str, rounds: int, duration_ms: int) -> VerificationResult:
        cleaned = re.sub(r"```(?:json)?\s*|```", "", str(text or ""), flags=re.IGNORECASE).strip()
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(cleaned)
        except (TypeError, ValueError):
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    payload = json.loads(match.group())
                except ValueError:
                    payload = None
        if not isinstance(payload, dict):
            return VerificationResult(
                mode=mode, verdict="blocked", summary="Verifier 未返回可解析的结构化结论。",
                issues=[{"severity": "warning", "message": cleaned[:1200] or "empty response"}],
                rounds=rounds, duration_ms=duration_ms, raw_text=cleaned[:4000],
            )
        verdict = str(payload.get("verdict") or "blocked").strip().lower()
        if verdict not in {"pass", "needs_fix", "blocked"}:
            verdict = "blocked"
        try:
            confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return VerificationResult(
            mode=mode, verdict=verdict,
            summary=str(payload.get("summary") or "Verifier 未提供摘要。")[:4000],
            confidence=confidence,
            checks=list(payload.get("checks") or [])[:30],
            issues=list(payload.get("issues") or [])[:30], rounds=rounds,
            duration_ms=duration_ms, raw_text=cleaned[:4000],
        )

    def verify(self, *, mode: str, request: str, final_answer: str,
               change_set: dict[str, Any], tool_evidence: list[dict[str, Any]],
               read_tool: Callable[[str, dict[str, Any]], str] | None = None) -> VerificationResult:
        mode = mode if mode in VALID_VERIFICATION_MODES else "standard"
        if mode == "off":
            return VerificationResult(mode="off", verdict="pass", summary="用户已关闭独立验证。", confidence=1.0)
        started = time.monotonic()
        evidence = {
            "user_request": request[:12000],
            "lead_final_answer": final_answer[:6000],
            "change_set": change_set,
            "tool_evidence": tool_evidence[-80:],
        }
        system = (
            "You are AstraCode's independent verifier. The implementation agent has stopped. "
            "Judge the user's requested outcome from objective evidence; never trust the lead answer by itself. "
            "You are read-only and must not propose that unobserved work already happened. "
            "Return ONLY one JSON object with: verdict ('pass', 'needs_fix', or 'blocked'), confidence (0..1), "
            "summary, checks ([{name,status,evidence}]), and issues ([{severity,message,path?}]). "
            "Use 'needs_fix' for a concrete defect or unmet requirement. Use 'blocked' when evidence is insufficient. "
            + ("In strict mode, inspect relevant changed files with the read-only tools before deciding. "
               "Require direct evidence for important claims and flag missing test evidence for executable code."
               if mode == "strict" else
               "In standard mode, verify scope, requested artifacts, tool success, and obvious contradictions economically.")
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": json.dumps(evidence, ensure_ascii=False, default=str)[:90000]}]
        tools = READ_ONLY_TOOLS if mode == "strict" and read_tool else []
        max_rounds = 5 if tools else 1
        for round_no in range(1, max_rounds + 1):
            self._trace("verification_model_started", mode=mode, round=round_no)
            request_args: dict[str, Any] = {
                "model": self.model, "system": system, "messages": messages,
                "max_tokens": self.max_tokens,
            }
            # Some Anthropic-compatible providers reject an explicit empty
            # tools array. Standard verification does not need tools at all.
            if tools:
                request_args["tools"] = tools
            response = self.client.messages.create(**request_args)
            self._trace("verification_model_completed", mode=mode, round=round_no,
                        stop_reason=getattr(response, "stop_reason", None))
            messages.append({"role": "assistant", "content": response.content})
            tool_blocks = [block for block in response.content if self._value(block, "type") == "tool_use"]
            if not tool_blocks:
                duration = round((time.monotonic() - started) * 1000)
                result = self._parse(text_content(response.content), mode, round_no, duration)
                self._trace("verification_completed", **result.as_dict())
                return result
            results = []
            for block in tool_blocks:
                name = str(self._value(block, "name", ""))
                tool_id = str(self._value(block, "id", ""))
                args = self._value(block, "input", {}) or {}
                output = read_tool(name, args) if read_tool and name in {item["name"] for item in READ_ONLY_TOOLS} else "Error: verifier tool is not allowed"
                self._trace("verification_tool_completed", mode=mode, tool=name,
                            ok=not str(output).lower().startswith("error"), result=str(output)[:1200])
                results.append({"type": "tool_result", "tool_use_id": tool_id, "content": str(output)[:50000]})
            messages.append({"role": "user", "content": results})
        duration = round((time.monotonic() - started) * 1000)
        result = VerificationResult(mode=mode, verdict="blocked", summary="严格验证达到最大只读检查轮次。", rounds=max_rounds, duration_ms=duration)
        self._trace("verification_completed", **result.as_dict())
        return result
