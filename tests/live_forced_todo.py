"""Real DeepSeek Todo-mode CRUD acceptance suite.

Run manually. It creates only isolated directories under the system temp root,
removes them afterwards, and persists a redacted result summary.
"""
from __future__ import annotations

import json
import os
import io
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.app import AgentApp
from agent_harness.settings import Settings
from agent_harness.sidecar import JsonlWriter, SidecarService

BASE = Path(os.getenv("S_FULL_TEST_BASE") or tempfile.gettempdir()).resolve()
EVIDENCE = ROOT / "docs" / "project_docs" / "testing" / "evidence"


def run_case(name: str, setup: str | None, prompt: str, assertion) -> dict:
    workspace = Path(tempfile.mkdtemp(prefix=f"astracode_todo_{name}_", dir=BASE)).resolve()
    started = time.monotonic()
    result: dict = {"name": name}
    try:
        if setup is not None:
            (workspace / "todo_target.md").write_text(setup, encoding="utf-8")
        traces: list[dict] = []
        settings = replace(
            Settings.from_env(ROOT), workdir=workspace, state_root=workspace / ".runtime",
            permission_mode="full_access", fake_client=False, visual=False,
            thinking_enabled=True, reasoning_effort="high", max_rounds=8, max_seconds=300,
        )
        if not (settings.api_key or settings.auth_token):
            raise RuntimeError("DeepSeek API credential is not configured")
        app = AgentApp(settings, trace_callback=traces.append, require_todo=True)
        status = app.agent_loop([{"role": "user", "content": prompt}], finalize_memory=False)
        successful = [
            str(event.get("tool")) for event in traces
            if event.get("type") == "tool_evidence_recorded" and event.get("ok")
        ]
        failed = [
            str(event.get("tool")) for event in traces
            if event.get("type") == "tool_evidence_recorded" and not event.get("ok")
        ]
        done, total = app.todo.progress()
        outcome_ok = bool(assertion(workspace / "todo_target.md"))
        result.update({
            "status": status, "seconds": round(time.monotonic() - started, 2),
            "successful_tools": successful, "failed_tools": failed,
            "todo_calls": successful.count("TodoWrite"),
            "todo_progress": {"completed": done, "total": total},
            "outcome_ok": outcome_ok,
            "passed": status == "completed" and total >= 3 and done == total and outcome_ok,
        })
    except Exception as exc:
        result.update({"passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if workspace.is_relative_to(BASE) and workspace.name.startswith(f"astracode_todo_{name}_"):
            shutil.rmtree(workspace, ignore_errors=False)
        result["cleaned"] = not workspace.exists()
    return result


def run_sidecar_case() -> dict:
    """Exercise the same explicit todo_mode payload sent by the desktop UI."""
    name = "sidecar_pipeline"
    workspace = Path(tempfile.mkdtemp(prefix=f"astracode_todo_{name}_", dir=BASE)).resolve()
    started = time.monotonic()
    result: dict = {"name": name}
    service = None
    try:
        target = workspace / "todo_target.md"
        target.write_text("# 算法教程\n\n待补充。\n", encoding="utf-8")
        prompt = (
            "<execution-requirements>\n本轮必须使用 TodoWrite 工具；TodoWrite 只用于记录进度，"
            "不能代替 write_file、edit_file、bash 等实际工具。\n</execution-requirements>\n\n用户任务：\n"
            "能否在这个文档里面写一个算法教程，包括双指针几道最经典题目的介绍。使用 Python。"
            "目标文档是 todo_target.md；先读取，再编辑，最后回读验证。"
        )
        outgoing = io.StringIO()
        service = SidecarService(JsonlWriter(outgoing), data_dir=workspace / ".appdata")
        service.handle({
            "command": "start_task", "request_id": "live-sidecar-todo",
            "session_id": "live-sidecar-session", "workspace_key": "project:live",
            "workspace_mode": "project", "project_path": str(workspace),
            "prompt": prompt, "display_prompt": "在 todo_target.md 中补充双指针算法教程",
            "mode": "agent", "permission": "full_access", "model": "deepseek-v4-flash",
            "thinking_effort": "high", "todo_mode": True, "verification_mode": "off",
            "failure_rollback": True, "offline": False,
        })
        deadline = time.monotonic() + 330
        while service._task_thread and service._task_thread.is_alive() and time.monotonic() < deadline:
            service._task_thread.join(0.2)
        events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        contract_event = next((event for event in events if event.get("type") == "agent_run_started"), {})
        session_event = next((event for event in events if event.get("type") == "session_started"), {})
        todo_events = [event for event in events if event.get("type") == "todo_updated"]
        last_items = todo_events[-1].get("items", []) if todo_events else []
        final_todos = all(item.get("status") == "completed" for item in last_items) and len(last_items) >= 3
        completed = any(event.get("type") == "task_completed" for event in events)
        blocked_read_only = any(event.get("type") == "tool_blocked_by_task_contract" for event in events)
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        outcome_ok = "双指针" in text and "Python" in text
        contract = contract_event.get("contract") or {}
        result.update({
            "seconds": round(time.monotonic() - started, 2),
            "session_todo_mode": session_event.get("todo_mode"),
            "required_evidence": contract.get("required_evidence", []),
            "forbidden_tools": contract.get("forbidden_tools", []),
            "todo_updates": len(todo_events), "final_todo_count": len(last_items),
            "final_todos_completed": final_todos, "blocked_as_read_only": blocked_read_only,
            "task_completed": completed, "outcome_ok": outcome_ok,
            "passed": (
                completed and session_event.get("todo_mode") is True and final_todos and outcome_ok
                and contract.get("required_evidence") == ["mutation"]
                and not contract.get("forbidden_tools") and not blocked_read_only
            ),
        })
    except Exception as exc:
        result.update({"passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if service is not None:
            service.close()
        if workspace.is_relative_to(BASE) and workspace.name.startswith(f"astracode_todo_{name}_"):
            shutil.rmtree(workspace, ignore_errors=False)
        result["cleaned"] = not workspace.exists()
    return result


def main() -> int:
    if not BASE.is_dir():
        raise RuntimeError(f"Test base does not exist: {BASE}")
    if "--sidecar-only" in sys.argv:
        cases = [run_sidecar_case()]
    else:
        cases = [
            run_case(
                "create", None,
                "使用 TodoWrite 把任务拆成 3 步并依次完成：先确认文件目标；再用 write_file 创建 "
                "todo_target.md，内容为一份简短的 Python 双指针教程，包含原理和一道示例；最后用 read_file "
                "核对标题。每一步结束后更新清单，最终把全部 Todo 标为 completed。",
                lambda path: path.is_file() and "双指针" in path.read_text(encoding="utf-8"),
            ),
            run_case(
                "edit", "# Python 教程\n\n这里是初稿。\n",
                "使用 TodoWrite 把任务拆成 3 步并依次完成：读取 todo_target.md；用 edit_file 把标题改为 "
                "“Python 双指针实战教程”并增加一个“左右指针”小节；再用 read_file 核对。每一步结束后更新清单，"
                "最终把全部 Todo 标为 completed。",
                lambda path: path.is_file() and "Python 双指针实战教程" in path.read_text(encoding="utf-8")
                and "左右指针" in path.read_text(encoding="utf-8"),
            ),
            run_case(
                "delete", "# 待删除教程\n",
                "使用 TodoWrite 把任务拆成 3 步并依次完成：确认 todo_target.md 存在；用 delete_file 删除它；"
                "用 path_exists 确认文件不存在。每一步结束后更新清单，最终把全部 Todo 标为 completed。",
                lambda path: not path.exists(),
            ),
            run_sidecar_case(),
        ]
    report = {
        "suite": "AstraCode host-enforced Todo real API CRUD",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": "DeepSeek (configured application provider)",
        "cases": cases,
        "passed": all(case.get("passed") for case in cases),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"todo_mode_crud_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "evidence": str(path)}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
