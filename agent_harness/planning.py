"""Read-only planning loop and structured Plan V1 schema."""

from __future__ import annotations

import json
import time
import re
import uuid
from typing import Any, Callable

from .schemas import TOOLS
from .message_protocol import INTERRUPTED_TOOL_RESULT
from .ui import text_content


PLAN_STATES = {
    "planning", "waiting_for_review", "revising", "executing",
    "verifying", "completed", "cancelled", "failed",
}
READ_ONLY_PLAN_TOOLS = {
    "set_working_directory", "read_file", "list_directory", "path_exists",
}

PLAN_SYSTEM = """You are the read-only planning phase of a coding agent.
Your job is to inspect enough real project context to propose an executable plan. You may only use the supplied read-only tools. Never claim to have edited files, run tests, or completed implementation.

Planning rules:
1. Inspect the project selectively. Read files that establish architecture, constraints, and verification commands; do not inventory the entire repository.
2. Preserve the user's goal and constraints. State assumptions instead of inventing facts.
3. Each step must name its purpose, likely files, implementation action, and verification.
4. Include risks and an overall verification strategy.
5. Prefer 2-7 meaningful steps. Simple work may use 2-3 steps.

When inspection is sufficient, return ONLY one JSON object with this shape:
{
  "title": "short plan title",
  "summary": "what will change and why",
  "assumptions": ["..."],
  "steps": [
    {"title": "...", "description": "...", "files": ["path or area"], "verification": "..."}
  ],
  "risks": ["..."],
  "verification": ["..."]
}
Do not wrap the final JSON in markdown fences."""


def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(value[start:end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def normalize_plan(raw: dict[str, Any], request: str, *, plan_id: str | None = None,
                   revision: int = 1) -> dict[str, Any]:
    raw_steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    steps = []
    for index, item in enumerate(raw_steps[:8], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"步骤 {index}").strip()
        description = str(item.get("description") or title).strip()
        files = item.get("files") if isinstance(item.get("files"), list) else []
        steps.append({
            "id": f"step-{index}", "title": title, "description": description,
            "files": [str(path) for path in files[:12]],
            "verification": str(item.get("verification") or "检查该步骤的实际结果").strip(),
            "status": "pending",
        })
    if not steps:
        steps = [
            {"id": "step-1", "title": "确认相关实现与约束", "description": "阅读相关代码并确认修改边界。",
             "files": [], "verification": "记录依据和受影响范围", "status": "pending"},
            {"id": "step-2", "title": "实施并验证变更", "description": request,
             "files": [], "verification": "运行与变更对应的最小有效验证", "status": "pending"},
        ]
    string_list = lambda key: [str(item) for item in raw.get(key, [])[:12]] if isinstance(raw.get(key), list) else []
    return {
        "id": plan_id or f"plan-{uuid.uuid4().hex[:12]}",
        "revision": revision,
        "state": "waiting_for_review",
        "title": str(raw.get("title") or "执行计划").strip(),
        "summary": str(raw.get("summary") or f"为“{request}”生成的执行计划。").strip(),
        "request": request,
        "assumptions": string_list("assumptions"),
        "steps": steps,
        "risks": string_list("risks"),
        "verification": string_list("verification"),
    }


def plan_markdown(plan: dict[str, Any]) -> str:
    lines = [f"## {plan['title']}", "", str(plan.get("summary") or ""), "", "### 执行步骤", ""]
    for index, step in enumerate(plan.get("steps") or [], 1):
        lines.extend([f"{index}. **{step['title']}**", f"   {step['description']}"])
        if step.get("files"):
            lines.append(f"   - 可能涉及：{', '.join(step['files'])}")
        lines.append(f"   - 验证：{step['verification']}")
    if plan.get("risks"):
        lines.extend(["", "### 风险", "", *[f"- {item}" for item in plan["risks"]]])
    if plan.get("assumptions"):
        lines.extend(["", "### 假设", "", *[f"- {item}" for item in plan["assumptions"]]])
    lines.extend(["", "计划已进入待审阅状态。你可以批准执行、提出修改意见或取消。"])
    return "\n".join(lines)


def execution_prompt(plan: dict[str, Any]) -> str:
    executable = {key: value for key, value in plan.items() if key != "request"}
    return (
        "The read-only planning phase has ended. Execute the user-approved plan below and make the "
        "file changes described by its steps. Treat it as the current implementation contract. "
        "Use tools, update progress, verify the result, and report any necessary deviation instead of silently changing scope.\n\n"
        + json.dumps(executable, ensure_ascii=False, indent=2)
    )


class PlanRunner:
    def __init__(self, app, on_tool: Callable[[str, dict, Callable[[], str]], str] | None = None):
        self.app = app
        self.on_tool = on_tool
        self.tools = [tool for tool in TOOLS if tool["name"] in READ_ONLY_PLAN_TOOLS]

    def run(self, messages: list[dict[str, Any]], request: str, *, revision: int = 1,
            max_rounds: int = 7, max_tool_calls: int = 12) -> tuple[dict[str, Any], str]:
        tool_calls = 0
        force_final = False
        for round_no in range(max_rounds):
            self.app.repair_message_history(messages, phase="planning")
            if self.app.cancel_event.is_set():
                raise RuntimeError("planning cancelled")
            active_tools = [] if force_final else self.tools
            active_system = PLAN_SYSTEM + (
                "\n\nInspection is now complete. Do not request more tools. Return the final JSON object immediately."
                if force_final else ""
            )
            report, should_summarize = self.app.context.prepare(active_system, messages, active_tools)
            if should_summarize:
                messages[:] = self.app.auto_compact(messages)
            model_started = time.monotonic()
            self.app._trace(
                "model_call_started", phase="planning", round=round_no + 1,
                model=self.app.settings.model, message_count=len(messages),
                tool_count=len(active_tools), context=report.as_dict(),
            )
            try:
                response = self.app.client.messages.create(
                    model=self.app.settings.model, system=active_system, messages=messages,
                    tools=active_tools, max_tokens=min(self.app.settings.max_output_tokens, 16384),
                )
            except Exception as exc:
                self.app._trace(
                    "model_call_failed", phase="planning", round=round_no + 1,
                    error_type=type(exc).__name__, error_message=str(exc),
                    duration_ms=round((time.monotonic() - model_started) * 1000),
                )
                raise
            self.app._trace(
                "model_call_completed", phase="planning", round=round_no + 1,
                duration_ms=round((time.monotonic() - model_started) * 1000),
                **self.app._response_metadata(response),
            )
            messages.append({"role": "assistant", "content": response.content})
            tool_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
            if not tool_blocks:
                raw_text = text_content(response.content)
                plan = normalize_plan(_json_object(raw_text), request, revision=revision)
                return plan, plan_markdown(plan)
            results = []
            cancelled = False
            for block in tool_blocks:
                if self.app.cancel_event.is_set():
                    output = INTERRUPTED_TOOL_RESULT
                    cancelled = True
                elif block.name not in READ_ONLY_PLAN_TOOLS:
                    output = f"Error: {block.name} is unavailable during read-only planning."
                else:
                    execute = lambda b=block: self.app.execute_tool(b.name, b.input)
                    try:
                        output = self.on_tool(block.name, block.input, execute) if self.on_tool else execute()
                    except Exception as exc:
                        output = f"Error: Tool execution raised {type(exc).__name__}: {exc}"
                tool_calls += 1
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output or "")})
                cancelled |= self.app.cancel_event.is_set()
            messages.append({"role": "user", "content": results})
            if cancelled:
                raise RuntimeError("planning cancelled")
            if tool_calls >= max_tool_calls or round_no >= max_rounds - 2:
                force_final = True
                messages.append({
                    "role": "user",
                    "content": "<planning-budget>Read-only inspection is complete. Return the required final JSON now; do not request more tools.</planning-budget>",
                })
        plan = normalize_plan({}, request, revision=revision)
        return plan, plan_markdown(plan)
