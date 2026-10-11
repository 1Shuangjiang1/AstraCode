"""Task completion contracts and provider stop-reason handling.

An API stop reason describes generation, not whether an external task succeeded.
This module combines the stop reason with the user's intent, successful tool
evidence and the final visible answer.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


EVIDENCE_TOOLS = {
    "mutation": frozenset({"write_file", "edit_file", "delete_file"}),
    "command": frozenset({"bash", "background_run", "check_background"}),
    "inspection": frozenset({"read_file", "list_directory", "path_exists", "bash", "task"}),
    "delegation": frozenset({"task", "spawn_teammate"}),
}

_ZH_STRONG_MUTATION = re.compile(
    r"(?:删除|移除|新建|创建|新增|添加|修改|编辑|修复|实现|重构|改名|重命名|替换)"
    r"(?:(?!任务|计划|清单)[^，。；,;\n]){0,32}"
    r"(?:文件|文档|代码|脚本|页面|模块|配置|README|Markdown|功能|界面|项目|"
    r"[\w.-]+\.(?:md|py|js|ts|tsx|jsx|json|ya?ml|toml|txt|html|css))",
    re.IGNORECASE,
)
_ZH_WRITE_TARGET = re.compile(
    r"(?:写|生成|保存|输出).{0,24}(?:文件|文档|代码|脚本|页面|模块|配置|README|Markdown|md\b|\.md|\.py|\.js|\.ts)",
    re.IGNORECASE,
)
_ZH_TARGET_THEN_MUTATION = re.compile(
    r"(?:文件|文档|代码|脚本|页面|模块|配置|README|Markdown|md\b|\.md|\.py|\.js|\.ts)"
    r".{0,20}(?:里|内|中|里面)?\s*(?:写入|写|生成|保存|输出|添加|新增|修改|编辑|实现)",
    re.IGNORECASE,
)
_EN_MUTATION = re.compile(
    r"\b(?:create|write|edit|modify|update|delete|remove|rename|replace|fix|implement|refactor|add)\b"
    r".{0,50}\b(?:file|document|code|script|page|module|config|feature|markdown|readme)\b",
    re.IGNORECASE | re.DOTALL,
)
_ZH_COMMAND = re.compile(r"(?:^|请|帮我|去|并|然后|再|顺便)(?:你)?\s*(?:运行|执行|测试|构建|编译|安装|启动)(?!情况|方式|原理)")
_EN_COMMAND = re.compile(r"(?:^|\bplease\s+|\bthen\s+)\b(?:run|execute|test|build|compile|install|start)\b", re.IGNORECASE)
_ZH_INSPECTION = re.compile(r"(?:^|请|帮我|去|先|再|然后|只)(?:你)?\s*(?:检查|审查|排查|查看|读取|调研|分析).{0,24}(?:项目|目录|文件|代码|日志|实现|工作区)")
_EN_INSPECTION = re.compile(r"\b(?:inspect|review|investigate|read|analyze|analyse)\b.{0,40}\b(?:project|directory|file|code|log|workspace|implementation)\b", re.IGNORECASE)
_DELEGATION = re.compile(r"子\s*agent|子智能体|teammate|subagent|delegate", re.IGNORECASE)
_ZH_NEGATED_ACTION = re.compile(
    r"(?:不要|请勿|禁止|不得|无需|不需要|不可|不能)\s*(?:进行|再)?\s*"
    r"(?:写入|写|生成|保存|输出|删除|移除|新建|创建|新增|添加|修改|编辑|修复|实现|重构|改名|重命名|替换|运行|执行|测试|构建|编译|安装|启动)"
    r"[^，。；,;]{0,20}",
)
_EN_NEGATED_ACTION = re.compile(
    r"\b(?:do\s+not|don't|must\s+not|without)\s+"
    r"(?:write|create|save|delete|remove|add|modify|edit|fix|implement|refactor|run|execute|test|build|compile|install|start)(?:ing)?\b"
    r"[^,.;]{0,40}",
    re.IGNORECASE,
)
_ZH_FORBID_MUTATION = re.compile(
    r"(?:不要|请勿|禁止|不得|无需|不需要|不可|不能).{0,8}"
    r"(?:写入|写|生成|保存|输出|删除|移除|新建|创建|新增|添加|修改|编辑|修复|重构|改名|重命名|替换)"
)
_EN_FORBID_MUTATION = re.compile(
    r"\b(?:do\s+not|don't|must\s+not|without)\s+"
    r"(?:write|create|save|delete|remove|add|modify|edit|fix|refactor|rename|replace)(?:ing)?\b",
    re.IGNORECASE,
)
_SHELL_MUTATION = re.compile(
    r"\b(?:set-content|add-content|out-file|new-item|remove-item|copy-item|move-item|rename-item|"
    r"del|erase|rmdir|mkdir|md|rd)\b|(?:^|\s)(?:>|>>|2>|&>)",
    re.IGNORECASE,
)
_FUTURE_ONLY = re.compile(
    r"(?:现在|接下来|马上|随后).{0,18}(?:我来|将|会)(?:开始|继续|编写|创建|修改|处理|完成)|"
    r"(?:我先|先让我).{0,24}(?:查看|读取|检查|了解)|"
    r"\b(?:I(?:'ll| will)|let me)\s+(?:now\s+)?(?:create|write|edit|modify|implement|continue|inspect)\b",
    re.IGNORECASE | re.DOTALL,
)

_RUNTIME_DIRECTIVE = re.compile(
    r"<(?:execution-requirements|recovery-context|verifier-feedback)\b[^>]*>.*?"
    r"</(?:execution-requirements|recovery-context|verifier-feedback)>",
    re.IGNORECASE | re.DOTALL,
)


def user_intent_text(request: str) -> str:
    """Remove host-authored control blocks before inferring user intent.

    Runtime directives can contain phrases such as ``不能代替 write_file``.
    Treating those implementation notes as user constraints previously turned a
    write request into a read-only contract.
    """
    cleaned = _RUNTIME_DIRECTIVE.sub("", str(request or "")).strip()
    return re.sub(r"^(?:用户任务|User task)\s*[：:]\s*", "", cleaned, flags=re.IGNORECASE).strip()


def latest_user_request(messages: list) -> str:
    """Return the latest natural-language user turn, ignoring runtime control messages."""
    ignored = (
        "<background-results>", "<inbox>", "<completion-guard",
        "<todo-completion-guard", "<agent-continuation",
    )
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            content = message["content"].strip()
            if content and not content.startswith(ignored):
                return content
    return ""


def requests_filesystem_mutation(request: str) -> bool:
    request = user_intent_text(request)
    actionable = _EN_NEGATED_ACTION.sub("", _ZH_NEGATED_ACTION.sub("", request))
    return bool(
        _ZH_STRONG_MUTATION.search(actionable)
        or _ZH_WRITE_TARGET.search(actionable)
        or _ZH_TARGET_THEN_MUTATION.search(actionable)
        or _EN_MUTATION.search(actionable)
    )


def forbids_filesystem_mutation(request: str) -> bool:
    request = user_intent_text(request)
    explicit_read_only = bool(re.search(r"(?:整个任务|全程|本次任务|项目|工作区).{0,8}只读|只读模式", request))
    return bool(explicit_read_only or _ZH_FORBID_MUTATION.search(request) or _EN_FORBID_MUTATION.search(request))


def task_contract(request: str) -> list[str]:
    """Infer only high-confidence externally verifiable requirements."""
    request = user_intent_text(request)
    actionable = _EN_NEGATED_ACTION.sub("", _ZH_NEGATED_ACTION.sub("", request))
    required: list[str] = []
    if requests_filesystem_mutation(request):
        required.append("mutation")
    if _ZH_COMMAND.search(actionable) or _EN_COMMAND.search(actionable):
        required.append("command")
    if (_ZH_INSPECTION.search(actionable) or _EN_INSPECTION.search(actionable)) and "mutation" not in required:
        required.append("inspection")
    if _DELEGATION.search(actionable):
        required.append("delegation")
    return required


@dataclass(frozen=True)
class CompletionDecision:
    action: str  # complete | continue | incomplete | refused
    status: str
    reason: str
    missing_evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "action": self.action, "status": self.status, "reason": self.reason,
            "missing_evidence": list(self.missing_evidence),
        }


@dataclass
class CompletionGate:
    request: str
    max_continuations: int = 3
    required_evidence: list[str] = field(init=False)
    successful_tools: Counter = field(default_factory=Counter)
    failed_tools: Counter = field(default_factory=Counter)
    continuations: int = 0

    def __post_init__(self) -> None:
        self.required_evidence = task_contract(self.request)

    @property
    def requires_mutation(self) -> bool:
        return "mutation" in self.required_evidence

    @property
    def successful_mutations(self) -> list[str]:
        return [name for name in EVIDENCE_TOOLS["mutation"] for _ in range(self.successful_tools[name])]

    def contract_dict(self) -> dict:
        return {
            "required_evidence": list(self.required_evidence),
            "action_oriented": bool(self.required_evidence),
            "forbidden_tools": sorted(EVIDENCE_TOOLS["mutation"]) if forbids_filesystem_mutation(self.request) else [],
        }

    def tool_forbidden(self, name: str, args: dict | None = None) -> bool:
        if not forbids_filesystem_mutation(self.request):
            return False
        if name in EVIDENCE_TOOLS["mutation"]:
            return True
        return name in {"bash", "background_run"} and bool(
            _SHELL_MUTATION.search(str((args or {}).get("command", "")))
        )

    def record_tool_result(self, name: str, output: str, args: dict | None = None) -> None:
        normalized = str(output).strip().lower()
        target = self.failed_tools if normalized.startswith(("error", "permission denied")) else self.successful_tools
        target[name] += 1
        if target is self.successful_tools and name in {"bash", "background_run"} and _SHELL_MUTATION.search(
            str((args or {}).get("command", ""))
        ):
            target["shell_mutation"] += 1

    def missing_evidence(self) -> tuple[str, ...]:
        missing = []
        for kind in self.required_evidence:
            if kind == "mutation" and self.successful_tools["shell_mutation"]:
                continue
            if any(self.successful_tools[name] for name in EVIDENCE_TOOLS[kind]):
                continue
            if (
                kind == "mutation"
                and forbids_filesystem_mutation(self.request)
                and any(self.successful_tools[name] for name in EVIDENCE_TOOLS["delegation"])
                and any(self.successful_tools[name] for name in EVIDENCE_TOOLS["inspection"])
            ):
                continue
            missing.append(kind)
        return tuple(missing)

    def evaluate(self, stop_reason: str | None, answer: str) -> CompletionDecision:
        reason = str(stop_reason or "unknown")
        if reason in {"max_tokens", "model_context_window_exceeded"}:
            return CompletionDecision("continue", "running", "provider_output_truncated")
        if reason == "pause_turn":
            return CompletionDecision("continue", "running", "provider_paused_turn")
        if reason == "refusal":
            return CompletionDecision("refused", "refused", "provider_refusal")
        if reason not in {"end_turn", "stop"}:
            return CompletionDecision("incomplete", "incomplete", f"unsupported_stop_reason:{reason}")
        if not answer.strip():
            return CompletionDecision("continue", "running", "empty_final_answer")
        missing = self.missing_evidence()
        if missing:
            return CompletionDecision("continue", "running", "missing_required_tool_evidence", missing)
        if _FUTURE_ONLY.search(answer):
            return CompletionDecision("continue", "running", "future_action_only")
        return CompletionDecision("complete", "completed", "contract_satisfied")

    def can_continue(self) -> bool:
        return self.continuations < self.max_continuations

    def continuation_message(self, decision: CompletionDecision) -> str:
        self.continuations += 1
        if decision.reason == "provider_output_truncated":
            instruction = "Your response was truncated. Continue from the exact point it stopped and finish the task."
        elif decision.reason == "provider_paused_turn":
            instruction = "The provider paused this turn. Resume the same task and continue processing."
        elif decision.reason == "empty_final_answer":
            instruction = "No user-visible final answer was returned. Continue the task and provide a concrete result."
        elif decision.reason == "future_action_only":
            instruction = "You only announced a future action. Perform it now, then report the actual result."
        else:
            missing = ", ".join(decision.missing_evidence)
            allowed = "; ".join(
                f"{kind}: {', '.join(sorted(EVIDENCE_TOOLS[kind]))}" for kind in decision.missing_evidence
            )
            instruction = (
                f"The task is not complete. Missing successful evidence categories: {missing}. "
                f"Use an appropriate tool ({allowed}), then provide the concrete final result."
            )
        return f'<completion-guard attempt="{self.continuations}" reason="{decision.reason}">{instruction}</completion-guard>'
