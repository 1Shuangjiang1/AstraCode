from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

from .agents import SubagentRunner, TeammateManager
from .concurrency import WorkspaceCoordinator
from .completion import CompletionGate, latest_user_request
from .context import ContextManager, ContextPolicy, estimate_tokens
from .memory import MemoryStore
from .message_protocol import INTERRUPTED_TOOL_RESULT, repair_tool_protocol
from .permissions import PermissionEngine
from .schemas import TOOLS
from .settings import Settings, create_client
from .state import MessageBus, SkillLoader, TaskManager, TodoManager, atomic_write
from .ui import Console, content_blocks_summary, text_content, tool_label
from .workspace import BackgroundManager, ToolExecutor, WorkspaceTools


class AgentApp:
    def __init__(self, settings: Settings, client=None, permission_prompt=None,
                 cancel_event: threading.Event | None = None, chat_mode: bool = False,
                 compaction_callback=None, context_callback=None, trace_callback=None,
                 require_todo: bool = False):
        self.settings = settings
        self.chat_mode = chat_mode
        self.cancel_event = cancel_event or threading.Event()
        self.compaction_callback = compaction_callback
        self.context_callback = context_callback
        self.trace_callback = trace_callback
        self.require_todo = require_todo
        self.last_compaction: dict = {}
        self.client = client or create_client(settings)
        self.console = Console(settings.visual, settings.trace_output_limit)
        self.coordinator = WorkspaceCoordinator()
        self.permission = PermissionEngine(settings.workdir, settings.permission_mode,
                                           settings.allow_critical, permission_prompt,
                                           dynamic_workspace=chat_mode)
        self.workspace = WorkspaceTools(settings.workdir, self.coordinator, self.cancel_event,
                                        settings.command_timeout, unrestricted=chat_mode,
                                        require_directory_selection=chat_mode)
        self.executor = ToolExecutor(self.permission, self.console)
        self.todo = TodoManager()
        self.skills = SkillLoader(settings.skill_dirs)
        self.tasks = TaskManager(settings.task_dir)
        self.background = BackgroundManager(self.workspace, self.console)
        self.bus = MessageBus(settings.team_dir / "inbox")
        self.memory = MemoryStore(settings.memory_dir, self.client, settings.model, self.console)
        self.subagents = SubagentRunner(self.client, settings.model, self.workspace,
                                       self.executor, self.console, settings.max_output_tokens, self._trace)
        self.team = TeammateManager(settings.team_dir, self.client, settings.model, self.bus,
                                    self.tasks, self.workspace, self.executor, self.console,
                                    settings.poll_interval, settings.idle_timeout, settings.max_output_tokens,
                                    self._trace)
        self.shutdown_requests: dict[str, dict] = {}
        self.plan_requests: dict[str, dict] = {}
        self.tools = TOOLS
        self.context = ContextManager(
            settings.transcript_dir,
            ContextPolicy(input_budget=settings.token_threshold, output_reserve=settings.max_output_tokens),
        )
        self.handlers = self._build_handlers()

    def _trace(self, event_type: str, **payload) -> None:
        if self.trace_callback:
            self.trace_callback({"type": event_type, **payload})

    @staticmethod
    def _response_metadata(response) -> dict:
        content_types = Counter(str(getattr(block, "type", "unknown")) for block in response.content)
        usage = getattr(response, "usage", None)
        usage_fields = (
            "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
        )
        return {
            "response_id": getattr(response, "id", None),
            "response_model": getattr(response, "model", None),
            "stop_reason": getattr(response, "stop_reason", None),
            "stop_sequence": getattr(response, "stop_sequence", None),
            "content_types": dict(content_types),
            "text_chars": len(text_content(response.content)),
            "usage": {key: getattr(usage, key) for key in usage_fields if usage is not None and getattr(usage, key, None) is not None},
        }

    def _build_handlers(self) -> dict:
        return {
            "set_working_directory": self._set_working_directory,
            "bash": lambda command: self.workspace.bash(command, actor="lead"),
            "read_file": lambda path, limit=None: self.workspace.read(path, limit, "lead"),
            "list_directory": lambda path=".": self.workspace.list_directory(path, "lead"),
            "path_exists": lambda path: self.workspace.path_exists(path, "lead"),
            "write_file": lambda path, content: self.workspace.write(path, content, "lead"),
            "edit_file": lambda path, old_text, new_text: self.workspace.edit(path, old_text, new_text, "lead"),
            "delete_file": lambda path: self.workspace.delete_file(path, "lead"),
            "TodoWrite": lambda items: self.todo.update(items),
            "task": lambda prompt, agent_type="Explore": self.subagents.run(prompt, agent_type),
            "load_skill": lambda name: self.skills.load(name),
            "compress": lambda: "Compressing...",
            "background_run": lambda command, timeout=120: self.background.run(command, timeout, "lead"),
            "check_background": lambda task_id=None: self.background.check(task_id),
            "task_create": lambda subject, description="": self.tasks.create(subject, description),
            "task_get": lambda task_id: self.tasks.get(task_id),
            "task_update": lambda task_id, status=None, add_blocked_by=None, remove_blocked_by=None:
                self.tasks.update(task_id, status, add_blocked_by, remove_blocked_by),
            "task_list": lambda: self.tasks.list_all(),
            "spawn_teammate": lambda name, role, prompt: self.team.spawn(name, role, prompt),
            "list_teammates": lambda: self.team.list_all(),
            "send_message": lambda to, content, msg_type="message": self.bus.send("lead", to, content, msg_type),
            "read_inbox": lambda: json.dumps(self.bus.read_inbox("lead"), indent=2, ensure_ascii=False),
            "broadcast": lambda content: self.bus.broadcast("lead", content, self.team.member_names()),
            "shutdown_request": self.handle_shutdown_request,
            "plan_approval": self.handle_plan_review,
            "idle": lambda: "Lead does not idle.",
            "claim_task": lambda task_id: self.tasks.claim(task_id, "lead"),
        }

    def _set_working_directory(self, path: str) -> str:
        result = self.workspace.set_working_directory(path, "lead")
        if not result.startswith("Error:"):
            self.permission.set_workdir(self.workspace.workdir)
        return result

    def build_system(self, messages: list | None = None) -> str:
        index = self.memory.index()
        relevant = self.memory.relevant_xml(messages or [])
        return (
            f"You are a coding agent at {self.settings.workdir}. Use tools to solve tasks.\n"
            + ("This is chat workspace mode. There is no active filesystem directory yet. "
               "For ordinary conversation, answer without filesystem tools. Before any file or shell work, "
               "call set_working_directory with an absolute directory path; the harness will request approval when required.\n"
               if self.chat_mode else
               "This is project workspace mode. Keep all file work inside the selected project.\n")
            + "The host is Windows and the bash tool runs non-interactive PowerShell, not POSIX bash. "
            "Use PowerShell syntax. Prefer read_file, list_directory, path_exists, write_file, edit_file, "
            "and delete_file over shell commands for file CRUD.\n"
            "Commands must terminate. Never start a watcher, server, REPL, or interactive process unless the user asks. "
            "After a successful change, perform at most one useful verification and then answer. "
            "A progress announcement such as 'I will now write it' is not a completed task. When the user requests "
            "a file change, use a mutation tool and only finish after that tool succeeds. "
            "An absent path after deletion means deletion succeeded; do not retry or turn that into an error.\n"
            f"Permission mode: {self.permission.mode}. Tool execution is enforced by the harness.\n"
            + (
                "TODO MODE IS ACTIVE. Before any other task tool, call TodoWrite with 3-7 concrete, "
                "verifiable steps. Keep exactly one item in_progress while work remains. Perform the actual "
                "work with file or command tools, update TodoWrite after each step, and mark every item completed "
                "before the final answer. The host rejects work tools before TodoWrite and rejects completion while "
                "todos remain open. Do not use task_create/task_update/task_list as a substitute for TodoWrite.\n"
                if self.require_todo else
                "Prefer task_create/task_update/task_list for multi-step work. Use TodoWrite for short checklists.\n"
            )
            + "Use task for subagent delegation. Use load_skill for specialized knowledge.\n"
            f"Skills:\n{self.skills.descriptions()}"
            + (f"\n\nMemory index:\n{index}" if index else "")
            + (f"\n\n{relevant}" if relevant else "")
        )

    def handle_shutdown_request(self, teammate: str) -> str:
        request_id = uuid.uuid4().hex[:8]
        self.shutdown_requests[request_id] = {"target": teammate, "status": "pending"}
        self.bus.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": request_id})
        return f"Shutdown request {request_id} sent to '{teammate}'"

    def handle_plan_review(self, request_id: str, approve: bool, feedback: str = "") -> str:
        request = self.plan_requests.get(request_id)
        if not request:
            return f"Error: Unknown plan request_id '{request_id}'"
        request["status"] = "approved" if approve else "rejected"
        self.bus.send("lead", request["from"], feedback, "plan_approval_response",
                      {"request_id": request_id, "approve": approve, "feedback": feedback})
        return f"Plan {request['status']} for '{request['from']}'"

    @staticmethod
    def estimate_tokens(messages: list) -> int:
        return estimate_tokens(messages)

    @staticmethod
    def microcompact(messages: list):
        """Compatibility shim; compaction now lives in ContextManager.prepare()."""
        return None

    def auto_compact(self, messages: list) -> list:
        self.settings.transcript_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.transcript_dir / f"transcript_{int(time.time())}_{uuid.uuid4().hex[:6]}.jsonl"
        body = "".join(json.dumps(message, default=str, ensure_ascii=False) + "\n" for message in messages)
        atomic_write(path, body)
        target = max(1, len(messages) - 12)
        prompt_boundaries = [
            index for index, message in enumerate(messages)
            if message.get("role") == "user" and isinstance(message.get("content"), str)
        ]
        candidates = [index for index in prompt_boundaries if index >= target]
        cut = candidates[0] if candidates else (prompt_boundaries[-1] if prompt_boundaries else 0)
        if cut <= 0:
            older, recent = list(messages), []
        else:
            older, recent = list(messages[:cut]), list(messages[cut:])
        response = self.client.messages.create(
            model=self.settings.model,
            messages=[{"role": "user", "content":
                       "Summarize this coding-agent conversation for exact continuity. Preserve: the user's goal and constraints; decisions; files read or changed; commands and verification results; current working directory; open todos; errors; and concrete next steps. Do not invent facts.\n\n" +
                       json.dumps(older, default=str, ensure_ascii=False)[-80000:]}],
            max_tokens=2000,
        )
        summary = text_content(response.content)
        if not summary:
            summary = "No textual summary was returned."
        summary_block = f"<conversation-summary transcript=\"{path}\">\n{summary}\n</conversation-summary>"
        if recent and recent[0].get("role") == "user" and isinstance(recent[0].get("content"), str):
            recent[0] = {**recent[0], "content": f"{summary_block}\n\n{recent[0]['content']}"}
            compacted = recent
        else:
            compacted = [{"role": "user", "content": summary_block}] + recent
        self.last_compaction = {
            "summary": summary, "transcript": str(path), "originalMessages": len(messages),
            "compactedMessages": len(compacted), "estimatedTokens": self.estimate_tokens(compacted),
        }
        if self.compaction_callback:
            self.compaction_callback(dict(self.last_compaction))
        return compacted

    def execute_tool(self, name: str, args: dict, actor: str = "lead") -> str:
        handler = self.handlers.get(name)
        if not handler:
            return f"Unknown tool: {name}"
        return self.executor.execute(name, args, handler, actor)

    @staticmethod
    def _todo_contract_error(args: dict) -> str | None:
        items = args.get("items")
        if not isinstance(items, list) or not 3 <= len(items) <= 7:
            return "Todo mode requires one checklist containing 3-7 items."
        statuses = [str(item.get("status", "pending")).lower() for item in items if isinstance(item, dict)]
        if len(statuses) != len(items):
            return "Every Todo item must be an object."
        open_items = any(status != "completed" for status in statuses)
        in_progress = sum(status == "in_progress" for status in statuses)
        if open_items and in_progress != 1:
            return "Todo mode requires exactly one in_progress item while work remains."
        if not open_items and in_progress:
            return "A fully completed Todo list cannot contain an in_progress item."
        return None

    def repair_message_history(self, messages: list, *, phase: str = "agent") -> dict:
        report = repair_tool_protocol(messages)
        if report["changed"]:
            self._trace("message_protocol_repaired", phase=phase, **report)
        return report

    def agent_loop(self, messages: list, max_rounds: int | None = None,
                   max_seconds: float | None = None, finalize_memory: bool = True):
        max_rounds = self.settings.max_rounds if max_rounds is None else max_rounds
        if self.require_todo:
            # A 3-7 step checklist normally needs several alternating work and
            # status-update turns; the regular eight-round budget is too small.
            max_rounds = max(max_rounds, 16)
        max_seconds = self.settings.max_seconds if max_seconds is None else max_seconds
        deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
        rounds_without_todo = 0
        failed_calls: dict[str, int] = {}
        completion = CompletionGate(latest_user_request(messages))
        run_started = time.monotonic()
        self._trace(
            "agent_run_started", contract=completion.contract_dict(), todo_mode=self.require_todo,
            max_rounds=max_rounds, max_seconds=max_seconds,
        )
        for round_no in range(1, max_rounds + 1 if max_rounds > 0 else 10**9):
            # Repair a previous interrupted run before either returning or calling the API.
            self.repair_message_history(messages)
            if self.cancel_event.is_set():
                self._trace("agent_run_finished", status="cancelled", round=round_no)
                return "cancelled"
            if deadline and time.monotonic() > deadline:
                self.console.log("停止", f"达到最大耗时 {max_seconds:.0f}s", color="yellow")
                self._trace("agent_run_finished", status="time_limit", round=round_no)
                return "time_limit"
            before = list(messages)
            notifications = self.background.drain()
            if notifications:
                text = "\n".join(f"[bg:{item['task_id']}] {item['status']}: {item['result']}" for item in notifications)
                messages.append({"role": "user", "content": f"<background-results>\n{text}\n</background-results>"})
            inbox = self.bus.read_inbox("lead")
            if inbox:
                messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox, ensure_ascii=False)}</inbox>"})
            system = self.build_system(messages)
            context_report, should_summarize = self.context.prepare(system, messages, self.tools)
            if context_report.compacted_results and self.context_callback:
                self.context_callback({"type": "context_trimmed", **context_report.as_dict()})
            if should_summarize:
                messages[:] = self.auto_compact(messages)
                system = self.build_system(messages)
                context_report, _ = self.context.prepare(system, messages, self.tools)
            self.console.log("模型调用", f"第 {round_no} 轮", {"model": self.settings.model,
                             "messages": len(messages), "tools": len(self.tools),
                             "context_tokens": context_report.request_tokens}, "cyan")
            model_started = time.monotonic()
            self._trace(
                "model_call_started", round=round_no, model=self.settings.model,
                message_count=len(messages), tool_count=len(self.tools), context=context_report.as_dict(),
            )
            try:
                response = self.client.messages.create(model=self.settings.model,
                    system=system, messages=messages, tools=self.tools,
                    max_tokens=self.settings.max_output_tokens)
            except Exception as exc:
                self._trace(
                    "model_call_failed", round=round_no, error_type=type(exc).__name__,
                    error_message=str(exc), duration_ms=round((time.monotonic() - model_started) * 1000),
                )
                raise
            self._trace(
                "model_call_completed", round=round_no,
                duration_ms=round((time.monotonic() - model_started) * 1000),
                **self._response_metadata(response),
            )
            if self.cancel_event.is_set():
                return "cancelled"
            messages.append({"role": "assistant", "content": response.content})
            self.console.log("模型返回", response.stop_reason, content_blocks_summary(response.content), "cyan")
            tool_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
            if not tool_blocks:
                if self.cancel_event.is_set():
                    self._trace("agent_run_finished", status="cancelled", round=round_no)
                    return "cancelled"
                answer = text_content(response.content)
                if self.require_todo and (not self.todo.has_items() or self.todo.has_open_items()):
                    done, total = self.todo.progress()
                    reason = "todo_not_initialized" if total == 0 else "todo_items_open"
                    self._trace(
                        "todo_completion_blocked", round=round_no, reason=reason,
                        completed=done, total=total,
                    )
                    if completion.can_continue():
                        completion.continuations += 1
                        instruction = (
                            "Todo mode is active, but no TodoWrite checklist exists. Create the 3-7 step checklist now, "
                            "then perform the task."
                            if total == 0 else
                            f"Todo mode is active and only {done}/{total} items are completed. Continue the actual work "
                            "for the current item, update TodoWrite, and close every item before answering."
                        )
                        messages.append({
                            "role": "user",
                            "content": f'<todo-completion-guard reason="{reason}">{instruction}</todo-completion-guard>',
                        })
                        continue
                    self._trace("agent_run_finished", status="incomplete", round=round_no, reason=reason)
                    return "incomplete"
                decision = completion.evaluate(response.stop_reason, answer)
                self._trace(
                    "completion_evaluated", round=round_no, **decision.as_dict(),
                    contract=completion.contract_dict(), successful_tools=dict(completion.successful_tools),
                    failed_tools=dict(completion.failed_tools), continuation_count=completion.continuations,
                )
                if decision.action == "continue":
                    if completion.can_continue():
                        reminder = completion.continuation_message(decision)
                        messages.append({"role": "user", "content": reminder})
                        self.console.log(
                            "完成检查", "当前回包尚不满足任务完成条件，继续运行",
                            {"reason": decision.reason, "continuation": completion.continuations}, "yellow",
                        )
                        continue
                    self.console.log("停止", "多次继续后仍未满足完成条件", color="yellow")
                    self._trace("agent_run_finished", status="incomplete", round=round_no, reason=decision.reason)
                    return "incomplete"
                if decision.action != "complete":
                    self._trace("agent_run_finished", status=decision.status, round=round_no, reason=decision.reason)
                    return decision.status
                if finalize_memory:
                    self.memory.extract(before + [{"role": "assistant", "content": response.content}])
                    self.memory.consolidate()
                self._trace(
                    "agent_run_finished", status="completed", round=round_no,
                    duration_ms=round((time.monotonic() - run_started) * 1000),
                )
                return "completed"
            results, used_todo, manual_compress = [], False, False
            cancelled = False
            for block in tool_blocks:
                self.console.log("工具调用", tool_label(block.name), block.input, "yellow")
                manual_compress |= block.name == "compress"
                fingerprint = f"{block.name}:{json.dumps(block.input, sort_keys=True, ensure_ascii=False)}"
                if self.cancel_event.is_set():
                    output = INTERRUPTED_TOOL_RESULT
                    cancelled = True
                elif self.require_todo and block.name == "TodoWrite" and (
                    todo_error := self._todo_contract_error(block.input)
                ):
                    output = f"Error: {todo_error} Fix the checklist and call TodoWrite again."
                    self._trace(
                        "tool_blocked_by_todo_contract", round=round_no, tool=block.name,
                        reason="invalid_todo_state", args_keys=sorted(block.input.keys()),
                    )
                elif self.require_todo and not self.todo.has_items() and block.name != "TodoWrite":
                    output = (
                        "Error: Todo mode requires TodoWrite to initialize a 3-7 step checklist before any other task tool. "
                        "Call TodoWrite first, then retry this action."
                    )
                    self._trace(
                        "tool_blocked_by_todo_contract", round=round_no, tool=block.name,
                        reason="todo_not_initialized", args_keys=sorted(block.input.keys()),
                    )
                elif completion.tool_forbidden(block.name, block.input):
                    output = "Permission denied: the user's explicit task constraint forbids filesystem changes."
                    self._trace(
                        "tool_blocked_by_task_contract", round=round_no, tool=block.name,
                        reason="user_requested_read_only", args_keys=sorted(block.input.keys()),
                    )
                elif failed_calls.get(fingerprint, 0) >= 2:
                    output = "Error: Repeated failing tool call suppressed. Choose a different approach or finish."
                else:
                    try:
                        output = self.execute_tool(block.name, block.input)
                    except Exception as exc:
                        output = f"Error: Tool execution raised {type(exc).__name__}: {exc}"
                        self._trace(
                            "tool_execution_failed", round=round_no, tool=block.name,
                            error_type=type(exc).__name__, error_message=str(exc),
                        )
                output = str(output or "")
                if output.lower().startswith(("error", "permission denied")):
                    failed_calls[fingerprint] = failed_calls.get(fingerprint, 0) + 1
                else:
                    failed_calls.pop(fingerprint, None)
                completion.record_tool_result(block.name, output, block.input)
                self._trace(
                    "tool_evidence_recorded", round=round_no, tool=block.name,
                    ok=not output.lower().startswith(("error", "permission denied")),
                    output_chars=len(output), missing_evidence=list(completion.missing_evidence()),
                )
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                used_todo |= block.name == "TodoWrite"
                cancelled |= self.cancel_event.is_set()
            rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
            if self.todo.has_open_items() and rounds_without_todo >= 3:
                results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
            if response.stop_reason in {"max_tokens", "model_context_window_exceeded"}:
                results.append({
                    "type": "text",
                    "text": (
                        "<truncated-response>The provider truncated the previous response. "
                        "Retry any incomplete tool call with every required argument. Keep reasoning concise, "
                        "perform the requested action, and avoid repeating completed work.</truncated-response>"
                    ),
                })
            messages.append({"role": "user", "content": results})
            if cancelled:
                self._trace("agent_run_finished", status="cancelled", round=round_no)
                return "cancelled"
            if manual_compress:
                messages[:] = self.auto_compact(messages)
                continue
        self.console.log("停止", f"达到最大轮数 {max_rounds}", color="yellow")
        self._trace("agent_run_finished", status="round_limit", round=max_rounds)
        return "round_limit"

    def permission_status(self) -> str:
        critical = "允许" if self.permission.allow_critical else "硬拦截"
        return f"permission_mode={self.permission.mode}; critical={critical}"

    def repl(self):
        self.console.banner(self.settings.model, self.settings.workdir,
                            self.permission.mode, self.settings.fake_client)
        history = []
        while True:
            try:
                # A worker approval waits until the current REPL input is submitted,
                # then owns stdin before the next prompt is displayed.
                with self.permission.input_guard():
                    query = input("\033[36ms_full >> \033[0m")
            except (EOFError, KeyboardInterrupt):
                break
            command = query.strip()
            lower = command.lower()
            if lower in {"", "q", "exit"}:
                break
            if lower == "/visual off":
                self.console.enabled = False
                print("可视化追踪已关闭。")
                continue
            if lower == "/visual on":
                self.console.enabled = True
                self.console.banner(self.settings.model, self.settings.workdir,
                                    self.permission.mode, self.settings.fake_client)
                continue
            if lower == "/permissions":
                print(self.permission_status())
                continue
            if lower.startswith("/permissions "):
                try:
                    self.permission.set_mode(lower.split(maxsplit=1)[1])
                    print(self.permission_status())
                except ValueError as exc:
                    print(exc)
                continue
            if lower == "/compact":
                history[:] = self.auto_compact(history) if history else history
                print(f"History messages: {len(history)}")
                continue
            if lower == "/tasks":
                print(self.tasks.list_all())
                continue
            if lower == "/team":
                print(self.team.list_all())
                continue
            if lower == "/inbox":
                print(json.dumps(self.bus.read_inbox("lead"), indent=2, ensure_ascii=False))
                continue
            history.append({"role": "user", "content": query})
            self.agent_loop(history)
            content = history[-1].get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        print(block.text)
            print()


def create_app(workdir: Path | None = None, client=None, permission_prompt=None,
               settings: Settings | None = None) -> AgentApp:
    settings = settings or Settings.from_env(workdir)
    return AgentApp(settings, client, permission_prompt)
