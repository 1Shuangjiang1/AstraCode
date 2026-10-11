"""Real-provider acceptance test for verifier, diff/undo and recovery metadata."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_harness.app import AgentApp
from agent_harness.change_tracking import RunTransaction
from agent_harness.session_store import SessionStore
from agent_harness.settings import Settings
from agent_harness.verifier import Verifier

BASE = Path(os.getenv("S_FULL_TEST_BASE") or tempfile.gettempdir()).resolve()
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "project_docs" / "testing" / "evidence"


def response_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or []
        if isinstance(content, str):
            return content
        parts = [str(getattr(item, "text", "") or (item.get("text", "") if isinstance(item, dict) else "")) for item in content]
        if any(parts):
            return "\n".join(parts)
    return ""


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="astracode_live_new_", dir=BASE)).resolve()
    # Runtime/checkpoint data must stay outside the selected project, exactly
    # like the desktop app's LOCALAPPDATA storage, or it pollutes the diff.
    data = Path(tempfile.mkdtemp(prefix="astracode_live_state_", dir=BASE)).resolve()
    report: dict = {"suite": "AstraCode verifier/change/recovery live", "workspace": str(root), "started_at": datetime.now().astimezone().isoformat(), "steps": []}
    try:
        settings = replace(
            Settings.from_env(PROJECT_ROOT), workdir=root, state_root=data / "agent-runtime",
            permission_mode="full_access", fake_client=False, visual=False,
            thinking_enabled=True, reasoning_effort="high", max_rounds=14,
            max_seconds=600, max_output_tokens=8192,
        )
        if not (settings.api_key or settings.auth_token):
            raise RuntimeError("DeepSeek API credential is not configured")
        traces: list[dict] = []
        app = AgentApp(settings, trace_callback=traces.append)
        transaction = RunTransaction(data / "runtime", "live-run")
        transaction.begin(root)
        messages = [{"role": "user", "content": (
            "在当前工作目录创建 mini_code_tutorial.md。写一份简洁的中文 Python 函数教程，"
            "必须包含 add(a, b) 示例和三条学习要点。请直接使用 write_file 创建，然后用 read_file 验证。"
        )}]
        started = time.monotonic()
        status = app.agent_loop(messages, finalize_memory=False)
        tutorial = root / "mini_code_tutorial.md"
        change_set = transaction.finish()
        created_ok = status == "completed" and tutorial.is_file() and "add" in tutorial.read_text(encoding="utf-8")
        report["steps"].append({"name": "real_agent_create", "passed": created_ok, "seconds": round(time.monotonic()-started, 2), "status": status})
        report["agent_tool_evidence"] = [
            {key: item.get(key) for key in ("tool", "ok", "summary", "reason")}
            for item in traces if item.get("type") == "tool_evidence_recorded"
        ]

        verifier_events: list[dict] = []
        verifier = Verifier(app.client, settings.model, 6000, verifier_events.append)
        def read_tool(name: str, args: dict) -> str:
            if name == "read_file": return app.workspace.read(str(args.get("path") or ""), args.get("limit"), "verifier")
            if name == "list_directory": return app.workspace.list_directory(str(args.get("path") or "."), "verifier")
            if name == "path_exists": return app.workspace.path_exists(str(args.get("path") or ""), "verifier")
            return "Error: not allowed"
        verification = verifier.verify(
            mode="strict", request=str(messages[0]["content"]), final_answer=response_text(messages),
            change_set=change_set, tool_evidence=[{"tool": "write_file", "ok": created_ok}, {"tool": "read_file", "ok": created_ok}],
            read_tool=read_tool,
        )
        report["steps"].append({"name": "real_ai_strict_verifier", "passed": verification.passed, "verdict": verification.verdict, "summary": verification.summary, "rounds": verification.rounds})
        report["steps"].append({"name": "diff_manifest", "passed": bool(change_set.get("files") and change_set.get("manifest_path") and change_set["totals"]["additions"] > 0), "totals": change_set.get("totals")})

        rollback = transaction.rollback()
        report["steps"].append({"name": "one_click_undo_core", "passed": rollback.get("ok") is True and not tutorial.exists(), "state": rollback.get("state")})

        store = SessionStore(data)
        store.ensure_session("live-session")
        store.create_run("interrupted-live", "live-session", "continue safely", {"verification_mode": "strict"})
        store.append_event({"type": "tool_started", "session_id": "live-session", "request_id": "interrupted-live", "tool_id": "pending-1", "tool": "write_file", "detail": "unknown outcome"})
        store.close()
        reopened = SessionStore(data)
        recovery = reopened.list_recoverable_runs("live-session")
        reopened.close()
        report["steps"].append({"name": "restart_recovery_checkpoint", "passed": len(recovery) == 1 and recovery[0]["checkpoint"].get("pending_tool", {}).get("tool") == "write_file", "state": recovery[0]["state"] if recovery else None})
        report["passed"] = all(step["passed"] for step in report["steps"])
        return_code = 0 if report["passed"] else 1
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    finally:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        evidence = EVIDENCE_DIR / f"verifier_changes_recovery_{datetime.now():%Y%m%d_%H%M%S}.json"
        report["cleaned"] = False
        if root.is_relative_to(BASE) and root.name.startswith("astracode_live_new_"):
            shutil.rmtree(root, ignore_errors=False)
        if data.is_relative_to(BASE) and data.name.startswith("astracode_live_state_"):
            shutil.rmtree(data, ignore_errors=False)
        report["cleaned"] = not root.exists() and not data.exists()
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({**report, "evidence": str(evidence)}, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
