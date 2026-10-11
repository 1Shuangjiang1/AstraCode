"""Long-running JSONL bridge used by the Tauri desktop application.

Protocol messages are written to stdout only. Diagnostics must use stderr so a
human-readable log line can never corrupt the desktop transport.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from .session_store import SessionStore
from .naming import fallback_title, generate_title


PROTOCOL_VERSION = 1
APP_VERSION = "0.8.1"
VALID_MODES = {"agent", "plan"}
VALID_PERMISSIONS = {"safe", "approval", "full_access"}
VALID_THINKING = {"none", "high", "max"}
VALID_WORKSPACES = {"project", "chat"}
VALID_VERIFICATION = {"off", "standard", "strict"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonlWriter:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._lock = threading.Lock()
        self.on_send: Callable[[dict[str, Any]], None] | None = None

    def send(self, event_type: str, **payload: Any) -> None:
        message = {"type": event_type, "timestamp": _timestamp(), **payload}
        with self._lock:
            self.stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.stream.flush()
        if self.on_send:
            try:
                self.on_send(message)
            except Exception as exc:
                print(f"event persistence failed: {exc}", file=sys.stderr, flush=True)


class SidecarService:
    """Desktop protocol host for AgentApp, Plan V1, persistence and approvals."""

    def __init__(self, writer: JsonlWriter, data_dir: Path | None = None,
                 store: SessionStore | None = None) -> None:
        self.writer = writer
        self.store = store or SessionStore(data_dir)
        self.writer.on_send = self._persist_event
        self._task_lock = threading.Lock()
        self._task_thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._shutdown = threading.Event()
        self._cancel_hook_lock = threading.Lock()
        self._cancel_hook: Callable[[], None] | None = None
        self._active_base: dict[str, str] | None = None
        self._cancel_notified = False
        self._approval_lock = threading.Lock()
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._approval_grants: dict[str, set[str]] = {}
        self._histories: dict[str, list[dict[str, Any]]] = {}
        self._chat_directories: dict[str, Path] = {}

    def _persist_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "session_deleted":
            return
        self.store.append_event(event)

    def handle(self, message: dict[str, Any]) -> bool:
        command = str(message.get("command", "")).strip()
        request_id = str(message.get("request_id") or uuid.uuid4())

        if command == "hello":
            self.writer.send(
                "ready",
                request_id=request_id,
                protocol_version=PROTOCOL_VERSION,
                app_version=APP_VERSION,
                capabilities={
                    "offline": True,
                    "modes": sorted(VALID_MODES),
                    "permissions": ["safe", "approval", "full_access"],
                    "thinking_efforts": ["none", "high", "max"],
                    "real_agent": True,
                    "plan_review": True,
                },
            )
            return True

        if command == "start_task":
            self._start_task(message, request_id)
            return True

        if command == "get_settings":
            self.writer.send("settings_snapshot", request_id=request_id, **self._settings_snapshot())
            return True

        if command == "get_tools":
            from .schemas import TOOLS
            self.writer.send(
                "tools_snapshot", request_id=request_id,
                tools=[{"name": tool["name"], "description": tool["description"]} for tool in TOOLS],
            )
            return True

        if command == "get_skills":
            from .settings import Settings
            from .state import SkillLoader
            root = Path(__file__).resolve().parent.parent
            settings = Settings.from_env(root)
            self.writer.send(
                "skills_snapshot", request_id=request_id,
                skills=SkillLoader(settings.skill_dirs).catalog(),
            )
            return True

        if command == "get_library":
            self.writer.send("library_snapshot", request_id=request_id, **self.store.list_library())
            return True

        if command == "get_recovery":
            self.writer.send("recovery_snapshot", request_id=request_id, runs=self.store.list_recoverable_runs())
            return True

        if command == "dismiss_recovery":
            target = str(message.get("target_request_id") or "")
            self.writer.send("recovery_dismissed", request_id=request_id, target_request_id=target,
                             ok=self.store.clear_recovery(target))
            return True

        if command == "get_change_set":
            target = str(message.get("target_request_id") or "")
            run = self.store.get_run(target)
            self.writer.send("change_set_snapshot", request_id=request_id, target_request_id=target,
                             session_id=(run or {}).get("session_id"), change_set=(run or {}).get("change_set") or {})
            return True

        if command == "undo_run":
            self._undo_run(message, request_id)
            return True

        if command == "resume_task":
            self._resume_task(message, request_id)
            return True

        if command == "save_library":
            projects = message.get("projects") or []
            sessions = message.get("conversations") or []
            if not isinstance(projects, list) or not isinstance(sessions, list):
                self.writer.send("error", request_id=request_id, code="invalid_library", message="项目和会话必须是列表。")
            else:
                self.store.save_library(projects, sessions)
                self.writer.send("library_saved", request_id=request_id, projects=len(projects), conversations=len(sessions))
            return True

        if command == "set_session_state":
            session_id = str(message.get("session_id") or "")
            ok = self.store.update_session_state(
                session_id,
                pinned=bool(message["pinned"]) if "pinned" in message else None,
                archived=bool(message["archived"]) if "archived" in message else None,
            )
            self.writer.send("session_state_saved", request_id=request_id, session_id=session_id, ok=ok)
            return True

        if command == "delete_session":
            session_id = str(message.get("session_id") or "")
            ok = self.store.delete_session(session_id)
            self._histories.pop(session_id, None)
            self._chat_directories.pop(session_id, None)
            self._approval_grants.pop(session_id, None)
            self.writer.send("session_deleted", request_id=request_id, session_id=session_id, ok=ok)
            return True

        if command == "update_settings":
            try:
                self._update_settings(message)
                self.writer.send("settings_snapshot", request_id=request_id, saved=True, **self._settings_snapshot())
            except Exception as exc:
                self.writer.send("error", request_id=request_id, code="settings_update_failed", message=str(exc))
            return True

        if command == "cancel_task":
            self._cancel.set()
            with self._cancel_hook_lock:
                cancel_hook = self._cancel_hook
            if cancel_hook:
                threading.Thread(target=self._run_cancel_hook, args=(cancel_hook,), daemon=True).start()
            self.writer.send("response", request_id=request_id, command=command, ok=True)
            self._notify_cancelled()
            return True

        if command == "approval_response":
            approval_id = str(message.get("approval_id", ""))
            choice = str(message.get("choice", "deny")).lower()
            mapped = {"once": "y", "always": "a", "deny": "n"}.get(choice, "n")
            with self._approval_lock:
                pending = self._pending_approvals.get(approval_id)
                if pending:
                    pending["choice"] = mapped
                    pending["event"].set()
            self.writer.send("response", request_id=request_id, command=command, ok=bool(pending))
            return True

        if command == "plan_response":
            self._handle_plan_response(message, request_id)
            return True

        if command == "shutdown":
            self._cancel.set()
            self._shutdown.set()
            self.writer.send("response", request_id=request_id, command=command, ok=True)
            return False

        self.writer.send(
            "error",
            request_id=request_id,
            code="unknown_command",
            message=f"不支持的 sidecar 命令：{command or '<empty>'}",
        )
        return True

    @staticmethod
    def _settings_snapshot() -> dict[str, Any]:
        from .settings import Settings
        root = Path(__file__).resolve().parent.parent
        settings = Settings.from_env(root)
        return {
            "model": settings.model,
            "title_model": settings.title_model,
            "title_base_url": settings.title_base_url,
            "title_api_key_configured": bool(settings.title_api_key),
            "base_url": settings.base_url or "https://api.deepseek.com/anthropic",
            "api_key_configured": bool(settings.api_key or settings.auth_token),
            "command_timeout": settings.command_timeout,
        }

    @staticmethod
    def _update_settings(message: dict[str, Any]) -> None:
        from .settings import user_config_path
        env_path = user_config_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        values: dict[str, str] = {}
        model = str(message.get("model", "")).strip()
        title_model = str(message.get("title_model", "")).strip()
        title_base_url = str(message.get("title_base_url", "")).strip()
        title_api_key = str(message.get("title_api_key", "")).strip()
        base_url = str(message.get("base_url", "")).strip()
        api_key = str(message.get("api_key", "")).strip()
        timeout = message.get("command_timeout")
        if model:
            values["S_FULL_MODEL"] = model
        if title_model:
            values["S_FULL_TITLE_MODEL"] = title_model
        if title_base_url:
            values["S_FULL_TITLE_BASE_URL"] = title_base_url
        if title_api_key:
            values["S_FULL_TITLE_API_KEY"] = title_api_key
        if base_url:
            values["ANTHROPIC_BASE_URL"] = base_url
        if api_key:
            values["ANTHROPIC_API_KEY"] = api_key
            # A newly supplied API key must take precedence over any legacy auth token.
            values["ANTHROPIC_AUTH_TOKEN"] = ""
        if timeout is not None:
            parsed = max(5, min(600, int(timeout)))
            values["S_FULL_COMMAND_TIMEOUT"] = str(parsed)
        if any("\n" in value or "\r" in value for value in values.values()):
            raise ValueError("配置值不能包含换行符。")
        existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        remaining = dict(values)
        output: list[str] = []
        for line in existing:
            key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        output.extend(f"{key}={value}" for key, value in remaining.items())
        temp = env_path.with_suffix(".env.tmp")
        temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        os.replace(temp, env_path)
        for key, value in values.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def _resume_task(self, message: dict[str, Any], request_id: str) -> None:
        target = str(message.get("target_request_id") or "")
        previous = self.store.get_run(target)
        if not previous or not previous.get("recoverable"):
            self.writer.send("error", request_id=request_id, code="run_not_recoverable", message="没有可继续的中断任务。")
            return
        config = dict(previous.get("config") or {})
        checkpoint = previous.get("checkpoint") or {}
        pending = checkpoint.get("pending_tool")
        completed = checkpoint.get("completed_tools") or []
        recovery = (
            f"<recovery-context previous_run=\"{target}\">\n"
            "The previous run was interrupted. Inspect the current workspace before changing anything. "
            "Do not blindly replay prior tool calls. Treat a pending tool as having an unknown outcome and verify it first.\n"
            f"Last phase: {previous.get('phase')}; last event: {checkpoint.get('last_event')}; "
            f"pending tool: {json.dumps(pending, ensure_ascii=False)}; "
            f"completed tool summaries: {json.dumps(completed[-20:], ensure_ascii=False)}\n"
            "Continue the original user task from the observed state and perform only missing work.\n"
            "</recovery-context>\n\n"
        )
        resumed = {
            "command": "start_task", "request_id": request_id,
            "session_id": previous["session_id"], "workspace_key": config.get("workspace_key", "chat"),
            "workspace_mode": config.get("workspace_mode", "project"),
            "project_path": config.get("project_path", ""), "display_prompt": "继续上次中断的任务",
            "prompt": recovery + str(previous.get("prompt") or ""), "mode": config.get("mode", "agent"),
            "permission": config.get("permission", "approval"), "model": config.get("model", ""),
            "thinking_effort": config.get("thinking_effort", "high"),
            "todo_mode": bool(config.get("todo_mode", False)),
            "verification_mode": config.get("verification_mode", "standard"),
            "failure_rollback": config.get("failure_rollback", True),
            "offline": bool(config.get("offline", False)), "resume_from": target,
        }
        self._start_task(resumed, request_id)

    def _undo_run(self, message: dict[str, Any], request_id: str) -> None:
        from .change_tracking import RunTransaction
        target = str(message.get("target_request_id") or "")
        run = self.store.get_run(target)
        base = {"request_id": request_id, "target_request_id": target,
                "session_id": str((run or {}).get("session_id") or "")}
        change_set = (run or {}).get("change_set") or {}
        manifest_value = str(change_set.get("manifest_path") or "")
        if not run or not manifest_value:
            self.writer.send("rollback_completed", **base, ok=False, error="没有可撤销的本轮文件检查点。")
            return
        manifest = Path(manifest_value).resolve()
        expected_root = self.store.sessions_dir.resolve()
        if not manifest.is_relative_to(expected_root) or not manifest.is_file():
            self.writer.send("rollback_completed", **base, ok=False, error="检查点路径无效或已过期。")
            return
        try:
            transaction = RunTransaction.load(manifest)
            result = transaction.rollback()
            updated = dict(change_set); updated["state"] = result["state"]; updated["rollback"] = result
            self.store.update_run(target, change_set=updated)
            self.writer.send("rollback_completed", **base, **result, change_set=updated)
        except Exception as exc:
            self.writer.send("rollback_completed", **base, ok=False, error=f"撤销失败：{exc}")

    def _start_task(self, message: dict[str, Any], request_id: str) -> None:
        prompt = str(message.get("prompt", "")).strip()
        display_prompt = str(message.get("display_prompt") or prompt).strip()
        mode = str(message.get("mode", "agent")).strip().lower()
        permission = str(message.get("permission", "approval")).strip().lower()
        thinking_effort = str(message.get("thinking_effort", "high")).strip().lower()
        workspace_mode = str(message.get("workspace_mode", "project")).strip().lower()
        offline = bool(message.get("offline", True))
        project_value = str(message.get("project_path", "")).strip()
        verification_mode = str(message.get("verification_mode", "standard")).strip().lower()
        failure_rollback = bool(message.get("failure_rollback", True))
        todo_mode = bool(message.get("todo_mode", False))
        resume_from = str(message.get("resume_from") or "") or None

        if not prompt:
            self.writer.send("error", request_id=request_id, code="empty_prompt", message="任务内容不能为空。")
            return
        if mode not in VALID_MODES:
            self.writer.send("error", request_id=request_id, code="invalid_mode", message=f"未知模式：{mode}")
            return
        if permission not in VALID_PERMISSIONS:
            self.writer.send(
                "error", request_id=request_id, code="invalid_permission", message=f"未知权限模式：{permission}"
            )
            return
        if thinking_effort not in VALID_THINKING:
            self.writer.send(
                "error", request_id=request_id, code="invalid_thinking_effort",
                message=f"未知思考强度：{thinking_effort}"
            )
            return
        if workspace_mode not in VALID_WORKSPACES:
            self.writer.send(
                "error", request_id=request_id, code="invalid_workspace_mode",
                message=f"未知工作空间模式：{workspace_mode}"
            )
            return
        if verification_mode not in VALID_VERIFICATION:
            self.writer.send("error", request_id=request_id, code="invalid_verification_mode",
                             message=f"未知验证模式：{verification_mode}")
            return

        project = (Path(project_value).expanduser().resolve() if project_value
                   else Path(__file__).resolve().parent.parent)
        if workspace_mode == "project" and not project_value:
            self.writer.send(
                "error", request_id=request_id, code="project_required", message="项目模式需要选择工作目录。"
            )
            return
        if not project.is_dir():
            self.writer.send(
                "error", request_id=request_id, code="invalid_project", message="所选项目文件夹不存在。"
            )
            return

        with self._task_lock:
            if self._task_thread and self._task_thread.is_alive():
                self.writer.send(
                    "error", request_id=request_id, code="task_busy", message="当前已有任务运行，请先等待或取消。"
                )
                return
            self._cancel = threading.Event()
            session_id = str(message.get("session_id") or f"session-{uuid.uuid4().hex[:10]}")
            workspace_key = str(message.get("workspace_key") or ("chat" if workspace_mode == "chat" else "project:unknown"))
            self.store.ensure_session(
                session_id, workspace_key, model=str(message.get("model", "")), permission=permission,
                thinking_effort=thinking_effort, project_path=str(project), status="running",
            )
            run_config = {
                "workspace_key": workspace_key, "workspace_mode": workspace_mode, "project_path": str(project),
                "mode": mode, "permission": permission, "model": str(message.get("model", "")),
                "thinking_effort": thinking_effort, "verification_mode": verification_mode,
                "todo_mode": todo_mode, "failure_rollback": failure_rollback, "offline": offline,
            }
            self.store.create_run(request_id, session_id, prompt, run_config, parent_request_id=resume_from)
            if resume_from:
                self.store.clear_recovery(resume_from)
            self.store.append_message(session_id, "user", display_prompt, message_id=request_id)
            self.store.append_event({"type": "user_message", "timestamp": _timestamp(), "session_id": session_id, "request_id": request_id, "content": display_prompt})
            self._active_base = {"request_id": request_id, "session_id": session_id}
            self._cancel_notified = False
            self.writer.send("response", request_id=request_id, command="start_task", ok=True, session_id=session_id)
            target = self._run_offline_task if offline else self._run_online_task
            self._task_thread = threading.Thread(
                target=target,
                args=(request_id, session_id, project, prompt, mode, permission,
                      str(message.get("model", "")), thinking_effort, workspace_mode,
                      todo_mode, None, verification_mode, failure_rollback, resume_from),
                name=f"sidecar-{session_id}",
                daemon=True,
            )
            if offline:
                self._maybe_name_session(request_id, session_id, prompt, offline=True, project=project)
            self._task_thread.start()
            if not offline:
                threading.Thread(
                    target=self._maybe_name_session,
                    kwargs={
                        "request_id": request_id, "session_id": session_id, "prompt": prompt,
                        "offline": False, "project": project,
                    },
                    name=f"title-{session_id}", daemon=True,
                ).start()

    def _run_offline_task(
        self,
        request_id: str,
        session_id: str,
        project: Path,
        prompt: str,
        mode: str,
        permission: str,
        model: str,
        thinking_effort: str,
        workspace_mode: str,
        todo_mode: bool = False,
        plan_id: str | None = None,
        verification_mode: str = "standard",
        failure_rollback: bool = True,
        resume_from: str | None = None,
    ) -> None:
        base = {"request_id": request_id, "session_id": session_id}
        if plan_id:
            self.store.update_plan_state(plan_id, "executing")
            self.writer.send("plan_state_changed", **base, plan_id=plan_id, state="executing")
        self.writer.send(
            "session_started",
            **base,
            project_path=str(project),
            workspace_mode=workspace_mode,
            mode=mode,
            permission=permission,
            model=model or "deepseek-v4-flash",
            offline=True,
            thinking_effort=thinking_effort,
            todo_mode=todo_mode,
            diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
        )
        self.writer.send("status", **base, phase="understanding", message="正在理解任务与工作区边界")
        if self._pause_or_cancel(base):
            return

        tool_id = f"tool-{uuid.uuid4().hex[:8]}"
        self.writer.send(
            "tool_started", **base, tool_id=tool_id, tool="inspect_workspace", label="检查项目结构", risk="low"
        )
        summary = self._inspect_project(project)
        if self._pause_or_cancel(base):
            return
        self.writer.send("tool_completed", **base, tool_id=tool_id, tool="inspect_workspace", ok=True, result=summary)

        if mode == "plan":
            from .planning import normalize_plan, plan_markdown
            previous = self.store.get_latest_plan(session_id)
            revision = int(previous.get("revision") or 0) + 1 if previous and previous.get("state") == "revising" else 1
            original_request = str(previous.get("request") or prompt) if revision > 1 else prompt
            plan = normalize_plan({
                "title": "离线执行计划",
                "summary": f"围绕“{original_request}”完成实现并验证。只读扫描结果：{summary}",
                "steps": [
                    {"title": "确认修改范围", "description": "阅读与目标直接相关的实现和约束。", "files": [], "verification": "列出依据和受影响区域"},
                    {"title": "实施计划变更", "description": original_request, "files": [], "verification": "检查实际文件差异"},
                    {"title": "运行验证", "description": "执行与变更相匹配的测试。", "files": [], "verification": "测试通过且无新增错误"},
                ],
                "risks": ["离线模式不会真实调用模型或修改文件"],
                "verification": ["启动在线模式后执行真实验证"],
            }, original_request, revision=revision)
            metadata = self._plan_metadata(project, workspace_mode, permission, model, thinking_effort, True,
                                           verification_mode, failure_rollback)
            self.store.save_plan(session_id, plan, metadata)
            self.writer.send(
                "plan_created",
                **base,
                **{key: value for key, value in plan.items() if key != "request"},
            )
            self.writer.send("plan_state_changed", **base, plan_id=plan["id"], state="waiting_for_review", revision=revision)
            answer = plan_markdown(plan)
        else:
            answer = (
                f"已收到任务：“{prompt}”。离线 MVP 完成了只读工作区检查：{summary}。"
                "界面与 Python sidecar 通信正常；接入真实 AgentApp 后，这里会显示实际工具调用和修改结果。"
            )

        history, summary_state = self.store.load_model_state(session_id)
        history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}])
        self.store.save_model_state(session_id, history, summary_state)
        self.writer.send("assistant_message", **base, content=answer)
        if plan_id:
            self.store.update_plan_state(plan_id, "verifying")
            self.writer.send("plan_state_changed", **base, plan_id=plan_id, state="verifying")
            completed = self.store.get_plan(plan_id)
            if completed:
                steps = [{**step, "status": "completed"} for step in completed.get("steps") or []]
                self.store.update_plan_state(plan_id, "completed", steps=steps)
            self.writer.send("plan_state_changed", **base, plan_id=plan_id, state="completed", steps=steps if completed else [])
        empty_changes = {"id": request_id, "state": "empty", "files": [],
                         "totals": {"files": 0, "additions": 0, "deletions": 0}}
        offline_verification = {"mode": verification_mode, "verdict": "pass", "passed": True,
                                "summary": "离线演示验证通过；未调用真实模型。", "confidence": 1.0,
                                "checks": [], "issues": [], "rounds": 0, "duration_ms": 0}
        self.store.update_run(request_id, change_set=empty_changes, verification=offline_verification)
        self.writer.send("change_set_ready", **base, change_set=empty_changes)
        self.writer.send("verification_completed", **base, **offline_verification)
        self.writer.send(
            "task_completed",
            **base,
            status="planned" if mode == "plan" else "completed",
            summary="离线桌面链路验证完成",
        )

    def _run_online_task(
        self,
        request_id: str,
        session_id: str,
        project: Path,
        prompt: str,
        mode: str,
        permission: str,
        model: str,
        thinking_effort: str,
        workspace_mode: str,
        todo_mode: bool = False,
        plan_id: str | None = None,
        verification_mode: str = "standard",
        failure_rollback: bool = True,
        resume_from: str | None = None,
    ) -> None:
        from .app import AgentApp
        from .change_tracking import RunTransaction
        from .settings import Settings
        from .verifier import Verifier

        base = {"request_id": request_id, "session_id": session_id}
        messages: list[dict[str, Any]] | None = None
        transaction = RunTransaction(self.store.runtime_dir(session_id), request_id)
        tool_evidence: list[dict[str, Any]] = []
        try:
            settings = Settings.from_env(project)
            settings = replace(
                settings,
                workdir=project,
                model=model or "deepseek-v4-flash",
                permission_mode=permission,
                fake_client=False,
                visual=False,
                thinking_enabled=thinking_effort != "none",
                reasoning_effort="max" if thinking_effort == "max" else "high",
                state_root=self.store.runtime_dir(session_id),
            )
            if not (settings.api_key or settings.auth_token):
                raise RuntimeError("尚未配置 DeepSeek API Key。")

            if workspace_mode == "project":
                checkpoint = transaction.begin(project)
                self.writer.send("change_checkpoint_created", **base, **checkpoint)

            self.writer.send(
                "session_started", **base, project_path=str(project), mode=mode,
                workspace_mode=workspace_mode,
                permission=permission, model=settings.model, offline=False,
                thinking_effort=thinking_effort, todo_mode=todo_mode,
                diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
            )
            self.writer.send("status", **base, phase="connecting", message="正在连接 DeepSeek V4 Flash")
            if self._cancel.is_set():
                self._notify_cancelled(base)
                return

            if mode == "plan":
                from .planning import PlanRunner
                def plan_compacted(info: dict[str, Any]) -> None:
                    self.writer.send("context_compacted", **base, **info)

                def plan_context_event(info: dict[str, Any]) -> None:
                    self.writer.send(info.pop("type", "context_trimmed"), **base, **info)

                def plan_trace_event(info: dict[str, Any]) -> None:
                    event_type = str(info.pop("type", "diagnostic_event"))
                    self.writer.send(event_type, **base, diagnostic=True, **info)

                plan_app = AgentApp(
                    settings, permission_prompt=self._request_approval, cancel_event=self._cancel,
                    chat_mode=workspace_mode == "chat", compaction_callback=plan_compacted,
                    context_callback=plan_context_event, trace_callback=plan_trace_event,
                    require_todo=False,
                )
                client = plan_app.client
                self._set_cancel_hook(client.close)
                stored_history, stored_summary = self.store.load_model_state(session_id)
                messages = stored_history
                messages.append({"role": "user", "content": prompt})
                previous = self.store.get_latest_plan(session_id)
                revision = int(previous.get("revision") or 0) + 1 if previous and previous.get("state") == "revising" else 1
                original_request = str(previous.get("request") or prompt) if revision > 1 else prompt

                def observed_plan_tool(name: str, args: dict, execute: Callable[[], str]) -> str:
                    tool_id = f"plan-tool-{uuid.uuid4().hex[:8]}"
                    detail = str(args.get("path") or "")[:600]
                    started = time.monotonic()
                    self.writer.send("tool_started", **base, tool_id=tool_id, tool=name, label=name,
                                     detail=detail, risk="low", planning=True)
                    result = execute()
                    self.writer.send("tool_completed", **base, tool_id=tool_id, tool=name,
                                     ok=not result.lower().startswith(("error", "permission denied")),
                                     result=result[:1200], duration_ms=round((time.monotonic() - started) * 1000),
                                     planning=True)
                    return result

                self.writer.send("plan_state_changed", **base, state="planning", revision=revision)
                plan, answer = PlanRunner(plan_app, observed_plan_tool).run(messages, original_request, revision=revision)
                metadata = self._plan_metadata(project, workspace_mode, permission, settings.model,
                                               thinking_effort, False, verification_mode, failure_rollback)
                self.store.save_plan(session_id, plan, metadata)
                self.store.save_model_state(session_id, messages, plan_app.last_compaction or stored_summary)
                self._histories[session_id] = messages
                self.writer.send(
                    "plan_created", **base, **{key: value for key, value in plan.items() if key != "request"},
                )
                self.writer.send("plan_state_changed", **base, plan_id=plan["id"], state="waiting_for_review", revision=revision)
                self.writer.send("assistant_message", **base, content=answer)
                self.writer.send("task_completed", **base, status="planned", summary="计划已生成，正在等待审阅")
                return

            def context_compacted(info: dict[str, Any]) -> None:
                self.writer.send("context_compacted", **base, **info)

            def context_event(info: dict[str, Any]) -> None:
                self.writer.send(info.pop("type", "context_trimmed"), **base, **info)

            def trace_event(info: dict[str, Any]) -> None:
                event_type = str(info.pop("type", "diagnostic_event"))
                self.writer.send(event_type, **base, diagnostic=True, **info)

            app = AgentApp(
                settings, permission_prompt=self._request_approval,
                cancel_event=self._cancel, chat_mode=workspace_mode == "chat",
                compaction_callback=context_compacted, context_callback=context_event,
                trace_callback=trace_event,
                require_todo=todo_mode,
            )
            if workspace_mode == "chat" and session_id in self._chat_directories:
                app.workspace.set_working_directory(str(self._chat_directories[session_id]), "session")
                app.permission.set_workdir(app.workspace.workdir)
                checkpoint = transaction.begin(app.workspace.workdir)
                self.writer.send("change_checkpoint_created", **base, **checkpoint)
            self._set_cancel_hook(lambda: (app.workspace.cancel_active(), app.client.close()))
            original_execute = app.execute_tool

            def observed_execute(name: str, args: dict, actor: str = "lead") -> str:
                if not transaction.started and app.workspace.directory_selected and name in {
                    "bash", "background_run", "write_file", "edit_file", "delete_file",
                }:
                    checkpoint = transaction.begin(app.workspace.workdir)
                    self.writer.send("change_checkpoint_created", **base, **checkpoint)
                tool_id = f"tool-{uuid.uuid4().hex[:8]}"
                detail = str(args.get("command") or args.get("path") or "")[:600]
                started = time.monotonic()
                self.writer.send(
                    "tool_started", **base, tool_id=tool_id, tool=name,
                    label=name, detail=detail,
                    risk=app.permission.assess(name, args).risk.name.lower(),
                )
                try:
                    result = original_execute(name, args, actor)
                except Exception as exc:
                    self.writer.send(
                        "tool_completed", **base, tool_id=tool_id, tool=name,
                        ok=False, result=str(exc)[:1200],
                        duration_ms=round((time.monotonic() - started) * 1000),
                    )
                    raise
                self.writer.send(
                    "tool_completed", **base, tool_id=tool_id, tool=name,
                    ok=not result.lower().startswith(("error", "permission denied")), result=result[:1200],
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                tool_evidence.append({
                    "tool": name, "actor": actor,
                    "ok": not result.lower().startswith(("error", "permission denied")),
                    "detail": detail, "result": result[:1200],
                })
                if name == "set_working_directory" and not result.startswith("Error:") and not transaction.started:
                    checkpoint = transaction.begin(app.workspace.workdir)
                    self.writer.send("change_checkpoint_created", **base, **checkpoint)
                if name == "TodoWrite" and not result.lower().startswith(("error", "permission denied")):
                    self.writer.send("todo_updated", **base, items=args.get("items") or [])
                return result

            app.execute_tool = observed_execute  # type: ignore[method-assign]
            if session_id not in self._histories:
                stored_history, _ = self.store.load_model_state(session_id)
                self._histories[session_id] = stored_history
            messages = self._histories[session_id]
            messages.append({"role": "user", "content": prompt})
            if plan_id:
                self.store.update_plan_state(plan_id, "executing")
                self.writer.send("plan_state_changed", **base, plan_id=plan_id, state="executing")
            self.writer.send("status", **base, phase="executing", message="DeepSeek 正在处理任务")
            # Desktop completion should not wait for additional hidden memory-model calls.
            result_status = app.agent_loop(messages, finalize_memory=False)
            if workspace_mode == "chat" and app.workspace.directory_selected:
                self._chat_directories[session_id] = app.workspace.workdir
            if self._cancel.is_set() or result_status == "cancelled":
                change_set = transaction.finish()
                self.store.update_run(request_id, change_set=change_set, state="cancelled", phase="interrupted", recoverable=True)
                self.writer.send("change_set_ready", **base, change_set=change_set)
                self.store.save_model_state(session_id, messages, app.last_compaction)
                if plan_id:
                    self.store.update_plan_state(plan_id, "cancelled")
                    self.writer.send("plan_state_changed", **base, plan_id=plan_id, state="cancelled")
                self._notify_cancelled(base)
                return

            answer = "任务已结束，但模型没有返回文本结果。"
            for message in reversed(messages):
                if message.get("role") == "assistant":
                    extracted = self._response_text(message.get("content", []))
                    if extracted:
                        answer = extracted
                    break

            change_set = transaction.finish()
            self.store.update_run(request_id, change_set=change_set)
            self.writer.send("change_set_ready", **base, change_set=change_set)

            verification_data: dict[str, Any] = {
                "mode": verification_mode, "verdict": "blocked", "passed": False,
                "summary": "主任务未完成，未进入独立验证。", "checks": [], "issues": [],
                "rounds": 0, "duration_ms": 0,
            }
            if result_status == "completed":
                def verifier_trace(info: dict[str, Any]) -> None:
                    event_type = str(info.pop("type", "verification_event"))
                    # The outer lifecycle emits the single authoritative final
                    # event after persistence/remediation has settled.
                    if event_type != "verification_completed":
                        self.writer.send(event_type, **base, **info)

                def verifier_read(name: str, args: dict[str, Any]) -> str:
                    if name == "read_file":
                        return app.workspace.read(str(args.get("path") or ""), args.get("limit"), "verifier")
                    if name == "list_directory":
                        return app.workspace.list_directory(str(args.get("path") or "."), "verifier")
                    if name == "path_exists":
                        return app.workspace.path_exists(str(args.get("path") or ""), "verifier")
                    return "Error: verifier tool is not allowed"

                verifier = Verifier(app.client, settings.model, min(settings.max_output_tokens, 8000), verifier_trace)
                self.writer.send("verification_started", **base, mode=verification_mode,
                                 message="独立 Verifier 正在检查需求、变更与工具证据")
                verification = verifier.verify(
                    mode=verification_mode, request=prompt, final_answer=answer,
                    change_set=change_set, tool_evidence=tool_evidence,
                    read_tool=verifier_read,
                )
                verification_data = verification.as_dict()

                if verification_mode == "strict" and not verification.passed and verification.verdict == "needs_fix":
                    self.writer.send("verification_remediation_started", **base, issues=verification.issues,
                                     message="严格验证发现可修复问题，主 Agent 将进行一次定向修复")
                    feedback = json.dumps({"summary": verification.summary, "issues": verification.issues}, ensure_ascii=False)
                    messages.append({
                        "role": "user",
                        "content": (
                            "<verifier-feedback>Independent strict verification found concrete issues. "
                            "Inspect the current workspace, fix only these issues, run appropriate verification, "
                            f"then report the actual result.\n{feedback}\n</verifier-feedback>"
                        ),
                    })
                    remediation_status = app.agent_loop(messages, max_rounds=min(settings.max_rounds, 6), finalize_memory=False)
                    if remediation_status == "completed":
                        result_status = "completed"
                        for message in reversed(messages):
                            if message.get("role") == "assistant":
                                extracted = self._response_text(message.get("content", []))
                                if extracted:
                                    answer = extracted
                                break
                        change_set = transaction.finish()
                        self.store.update_run(request_id, change_set=change_set)
                        self.writer.send("change_set_ready", **base, change_set=change_set, updated=True)
                        verification = verifier.verify(
                            mode="strict", request=prompt, final_answer=answer,
                            change_set=change_set, tool_evidence=tool_evidence,
                            read_tool=verifier_read,
                        )
                        verification_data = verification.as_dict()
                    else:
                        result_status = remediation_status
                if not verification_data.get("passed"):
                    result_status = "verification_failed"

            self.store.update_run(request_id, verification=verification_data)
            self.writer.send("verification_completed", **base, **verification_data)

            rollback_result: dict[str, Any] | None = None
            if result_status != "completed" and failure_rollback and change_set.get("files"):
                self.writer.send("rollback_started", **base, automatic=True, reason=result_status)
                rollback_result = transaction.rollback()
                change_set = {**change_set, "state": rollback_result["state"], "rollback": rollback_result}
                self.store.update_run(request_id, change_set=change_set)
                self.writer.send("rollback_completed", **base, automatic=True, **rollback_result, change_set=change_set)

            self.store.save_model_state(session_id, messages, app.last_compaction)
            self.writer.send("assistant_message", **base, content=answer)
            if plan_id:
                self.store.update_plan_state(plan_id, "verifying")
                self.writer.send("plan_state_changed", **base, plan_id=plan_id, state="verifying")
                stored_plan = self.store.get_plan(plan_id)
                final_state = "completed" if result_status == "completed" else "failed"
                steps = [{**step, "status": "completed" if final_state == "completed" else step.get("status", "pending")}
                         for step in (stored_plan.get("steps") or [])] if stored_plan else []
                self.store.update_plan_state(plan_id, final_state, steps=steps)
                self.writer.send("plan_state_changed", **base, plan_id=plan_id, state=final_state, steps=steps)
            if result_status != "completed":
                messages_by_status = {
                    "incomplete": "多次继续后仍未满足任务完成条件。",
                    "refused": "模型拒绝了本次请求，任务未执行。",
                    "time_limit": "任务达到最大运行时间，尚未完成。",
                    "round_limit": "任务达到最大模型轮次，尚未完成。",
                    "verification_failed": "独立 Verifier 未通过，本轮修改已按设置回滚。" if rollback_result else "独立 Verifier 未通过。",
                }
                self.writer.send(
                    "task_incomplete", **base, status=result_status,
                    message=messages_by_status.get(result_status, "任务未满足完成条件。"),
                    diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
                )
            else:
                self.writer.send(
                    "task_completed", **base, status=result_status,
                    summary="DeepSeek 在线任务已结束",
                    diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
                )
        except Exception as exc:
            transient = self._is_transient_failure(exc)
            change_set: dict[str, Any] | None = None
            try:
                if transaction.started:
                    change_set = transaction.finish()
                    self.store.update_run(request_id, change_set=change_set)
                    self.writer.send("change_set_ready", **base, change_set=change_set)
            except Exception as checkpoint_exc:
                print(f"change checkpoint finalization failed: {checkpoint_exc}", file=sys.stderr, flush=True)
            if plan_id:
                plan_state = "executing" if transient else "failed"
                self.store.update_plan_state(plan_id, plan_state)
                self.writer.send("plan_state_changed", **base, plan_id=plan_id, state=plan_state)
            if messages is not None:
                try:
                    self.store.save_model_state(session_id, messages)
                except Exception as persistence_exc:
                    print(f"history persistence failed: {persistence_exc}", file=sys.stderr, flush=True)
            if self._cancel.is_set():
                self._notify_cancelled(base)
                return
            print(f"online task failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            self.writer.send(
                "diagnostic_error", **base, diagnostic=True,
                error_type=type(exc).__name__, error_message=str(exc), traceback=traceback.format_exc(),
                diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
            )
            if transient:
                self.store.update_run(request_id, state="interrupted", phase="interrupted",
                                      recoverable=True, error=str(exc))
                self.writer.send(
                    "task_interrupted", **base, code="transient_provider_failure",
                    message="网络或服务暂时中断。已保存当前进度，可安全继续；系统不会盲目重放未确认的工具调用。",
                    error_message=str(exc), recoverable=True,
                    diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
                )
            else:
                rollback_result = None
                if failure_rollback and change_set and change_set.get("files"):
                    self.writer.send("rollback_started", **base, automatic=True, reason="runtime_failure")
                    rollback_result = transaction.rollback()
                    change_set = {**change_set, "state": rollback_result["state"], "rollback": rollback_result}
                    self.store.update_run(request_id, change_set=change_set)
                    self.writer.send("rollback_completed", **base, automatic=True, **rollback_result, change_set=change_set)
                self.store.update_run(request_id, state="failed", phase="failed", recoverable=False,
                                      error=str(exc), finished=True)
                self.writer.send(
                    "error", **base, code="online_task_failed",
                    message=f"DeepSeek 请求失败：{exc}",
                    diagnostic_log=str(self.store.run_log_path(session_id, request_id)),
                )
        finally:
            self._set_cancel_hook(None)

    def _maybe_name_session(self, request_id: str, session_id: str, prompt: str, *,
                            offline: bool, project: Path) -> None:
        if not self.store.should_generate_title(session_id):
            return
        source = "fallback"
        title = fallback_title(prompt)
        if not offline:
            from .settings import Settings
            try:
                # Provider credentials belong to the application, never to the
                # selected user's project. This prevents a project-level .env
                # from redirecting the title request to another endpoint.
                app_root = Path(__file__).resolve().parent.parent
                settings = Settings.from_env(app_root)
                title = generate_title(
                    settings.title_api_key or "",
                    settings.title_base_url,
                    settings.title_model,
                    prompt,
                    timeout=min(settings.api_timeout, 45),
                )
                source = "model"
            except Exception as exc:
                self.writer.send(
                    "title_generation_failed", request_id=request_id, session_id=session_id,
                    diagnostic=True, error_type=type(exc).__name__, error_message=str(exc),
                )
        if self.store.update_session_title(session_id, title):
            self.writer.send(
                "session_title_updated", request_id=request_id, session_id=session_id,
                title=title, source=source,
            )

    @staticmethod
    def _is_transient_failure(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        markers = (
            "timeout", "timed out", "connection", "connecterror", "network",
            "temporarily unavailable", "service unavailable", "rate limit", "429",
            "502", "503", "504", "remoteprotocolerror", "server disconnected",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _plan_metadata(project: Path, workspace_mode: str, permission: str, model: str,
                       thinking_effort: str, offline: bool,
                       verification_mode: str = "standard",
                       failure_rollback: bool = True) -> dict[str, Any]:
        return {
            "project_path": str(project), "workspace_mode": workspace_mode,
            "permission": permission, "model": model or "deepseek-v4-flash",
            "thinking_effort": thinking_effort, "offline": offline,
            "verification_mode": verification_mode, "failure_rollback": failure_rollback,
        }

    def _handle_plan_response(self, message: dict[str, Any], request_id: str) -> None:
        from .planning import execution_prompt

        plan_id = str(message.get("plan_id") or "")
        choice = str(message.get("choice") or "").lower()
        feedback = str(message.get("feedback") or "").strip()
        plan = self.store.get_plan(plan_id)
        if not plan or choice not in {"approve", "revise", "cancel"}:
            self.writer.send("error", request_id=request_id, code="invalid_plan_response",
                             message="计划不存在或审阅操作无效。")
            return
        session_id = str(plan["session_id"])
        metadata = plan.get("metadata") or {}
        base = {"request_id": request_id, "session_id": session_id, "plan_id": plan_id}
        if choice == "cancel":
            self.store.update_plan_state(plan_id, "cancelled")
            self.writer.send("response", **base, command="plan_response", ok=True)
            self.writer.send("plan_state_changed", **base, state="cancelled")
            return
        if choice == "revise":
            if not feedback:
                self.writer.send("error", **base, code="plan_feedback_required", message="请填写计划修改意见。")
                return
            self.store.update_plan_state(plan_id, "revising")
            self.writer.send("plan_state_changed", **base, state="revising", feedback=feedback)
            revised = {
                "command": "start_task", "request_id": request_id, "session_id": session_id,
                "workspace_key": str(message.get("workspace_key") or "chat"),
                "workspace_mode": metadata.get("workspace_mode", "project"),
                "project_path": metadata.get("project_path", ""), "prompt": f"修改计划：{feedback}",
                "mode": "plan", "permission": metadata.get("permission", "approval"),
                "model": metadata.get("model", "deepseek-v4-flash"),
                "thinking_effort": metadata.get("thinking_effort", "high"),
                "verification_mode": metadata.get("verification_mode", "standard"),
                "failure_rollback": bool(metadata.get("failure_rollback", True)),
                "offline": bool(metadata.get("offline", False)),
            }
            self._start_task(revised, request_id)
            return

        with self._task_lock:
            if self._task_thread and self._task_thread.is_alive():
                self.writer.send("error", **base, code="task_busy", message="当前已有任务运行。")
                return
            self._cancel = threading.Event()
            self._active_base = {"request_id": request_id, "session_id": session_id}
            self._cancel_notified = False
            self.store.update_plan_state(plan_id, "executing")
            run_config = dict(metadata)
            run_config["mode"] = "agent"
            self.store.create_run(request_id, session_id, execution_prompt(plan), run_config)
            self.writer.send("response", **base, command="plan_response", ok=True)
            self.writer.send("plan_state_changed", **base, state="executing")
            target = self._run_offline_task if bool(metadata.get("offline")) else self._run_online_task
            self._task_thread = threading.Thread(
                target=target,
                args=(request_id, session_id, Path(metadata.get("project_path") or ".").resolve(),
                      execution_prompt(plan), "agent", metadata.get("permission", "approval"),
                      metadata.get("model", "deepseek-v4-flash"), metadata.get("thinking_effort", "high"),
                      metadata.get("workspace_mode", "project"), False, plan_id,
                      metadata.get("verification_mode", "standard"),
                      bool(metadata.get("failure_rollback", True)), None),
                name=f"plan-execute-{session_id}", daemon=True,
            )
            self._task_thread.start()

    def _request_approval(self, tool_name: str, args: dict, decision, actor: str) -> str:
        session_id = str((self._active_base or {}).get("session_id", "global"))
        fingerprint = f"{tool_name}|{decision.risk.name}|{decision.reason}|{sorted(args.keys())}"
        if fingerprint in self._approval_grants.get(session_id, set()):
            return "y"
        approval_id = f"approval-{uuid.uuid4().hex[:10]}"
        event = threading.Event()
        safe_args = dict(args)
        if "content" in safe_args:
            safe_args["content"] = f"<{len(str(safe_args['content']))} characters>"
        pending = {"event": event, "choice": "n"}
        with self._approval_lock:
            self._pending_approvals[approval_id] = pending
        self.writer.send(
            "approval_required", **(self._active_base or {}), approval_id=approval_id,
            tool=tool_name, args=safe_args, actor=actor,
            risk=decision.risk.name.lower(), reason=decision.reason,
        )
        deadline = time.monotonic() + 120
        while not event.wait(0.1):
            if self._cancel.is_set() or time.monotonic() >= deadline:
                break
        with self._approval_lock:
            self._pending_approvals.pop(approval_id, None)
            if pending["choice"] == "a":
                self._approval_grants.setdefault(session_id, set()).add(fingerprint)
        return str(pending["choice"])

    def _set_cancel_hook(self, hook: Callable[[], None] | None) -> None:
        with self._cancel_hook_lock:
            self._cancel_hook = hook

    def close(self) -> None:
        self.writer.on_send = None
        self.store.close()

    @staticmethod
    def _run_cancel_hook(hook: Callable[[], None]) -> None:
        try:
            hook()
        except Exception as exc:
            print(f"cancel hook failed: {exc}", file=sys.stderr, flush=True)

    def _notify_cancelled(self, base: dict[str, str] | None = None) -> None:
        with self._cancel_hook_lock:
            if self._cancel_notified:
                return
            self._cancel_notified = True
            payload = base or self._active_base or {}
        self.writer.send("task_cancelled", **payload, message="任务已由用户停止")

    @staticmethod
    def _response_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        texts = []
        for block in content or []:
            block_type = getattr(block, "type", None)
            text = getattr(block, "text", None)
            if block_type == "text" and text:
                texts.append(str(text))
            elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                texts.append(str(block["text"]))
        return "\n".join(texts).strip()

    def _pause_or_cancel(self, base: dict[str, str]) -> bool:
        if self._cancel.wait(0.09):
            self._notify_cancelled(base)
            return True
        return False

    @staticmethod
    def _inspect_project(project: Path) -> str:
        counts: Counter[str] = Counter()
        file_count = 0
        directory_count = 0
        try:
            for root, directories, files in os.walk(project):
                directories[:] = [name for name in directories if name not in {".git", "node_modules", "target", "__pycache__"}]
                directory_count += len(directories)
                for name in files:
                    file_count += 1
                    suffix = Path(name).suffix.lower() or "[无扩展名]"
                    counts[suffix] += 1
                    if file_count >= 600:
                        break
                if file_count >= 600:
                    break
        except OSError:
            return "项目可访问，但部分目录无法读取"
        common = "、".join(f"{ext} {count}" for ext, count in counts.most_common(3)) or "暂无文件"
        capped = "（已达到快速扫描上限）" if file_count >= 600 else ""
        return f"发现 {directory_count} 个目录、{file_count} 个文件{capped}；主要类型：{common}"


def run(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, data_dir: Path | None = None) -> int:
    writer = JsonlWriter(stdout)
    service = SidecarService(writer, data_dir=data_dir)
    try:
        for raw_line in stdin:
            if service._shutdown.is_set():
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("消息必须是 JSON 对象")
            except (json.JSONDecodeError, ValueError) as exc:
                writer.send("error", code="invalid_json", message=str(exc))
                continue
            if not service.handle(message):
                break
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    # JSONL is always UTF-8, independent of the Windows console code page used
    # by the process that launched this sidecar.
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(run())
