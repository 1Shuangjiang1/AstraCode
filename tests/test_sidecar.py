import io
import json
import tempfile
import time
import unittest
import threading
from pathlib import Path

from agent_harness.sidecar import JsonlWriter, SidecarService, run


class SidecarTests(unittest.TestCase):
    def test_hello_and_shutdown_protocol(self):
        incoming = io.StringIO(
            '{"command":"hello","request_id":"hello-1"}\n'
            '{"command":"shutdown","request_id":"stop-1"}\n'
        )
        outgoing = io.StringIO()
        self.assertEqual(run(incoming, outgoing), 0)
        events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual(events[0]["type"], "ready")
        self.assertEqual(events[0]["protocol_version"], 1)
        self.assertTrue(events[0]["capabilities"]["offline"])
        self.assertEqual(events[1]["command"], "shutdown")

    def test_offline_agent_task_emits_complete_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "example.py").write_text("print('ok')", encoding="utf-8")
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing), data_dir=Path(temp) / "data")
            service.handle(
                {
                    "command": "start_task",
                    "request_id": "task-1",
                    "project_path": temp,
                    "prompt": "检查这个项目",
                    "mode": "agent",
                    "permission": "approval",
                }
            )
            deadline = time.monotonic() + 3
            while service._task_thread and service._task_thread.is_alive() and time.monotonic() < deadline:
                service._task_thread.join(0.05)
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            event_types = [event["type"] for event in events]
            self.assertIn("session_started", event_types)
            self.assertIn("session_title_updated", event_types)
            self.assertIn("tool_started", event_types)
            self.assertIn("tool_completed", event_types)
            self.assertIn("assistant_message", event_types)
            self.assertIn("change_set_ready", event_types)
            self.assertIn("verification_completed", event_types)
            self.assertEqual(event_types[-1], "task_completed")
            session_id = next(event["session_id"] for event in events if event["type"] == "session_started")
            generated = next(event for event in events if event["type"] == "session_title_updated")
            self.assertEqual(generated["source"], "fallback")
            history, _ = service.store.load_model_state(session_id)
            self.assertEqual([item["role"] for item in history], ["user", "assistant"])
            service.close()

    def test_todo_mode_is_persisted_in_run_config(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing), data_dir=Path(temp) / "data")
            service.handle({
                "command": "start_task", "request_id": "todo-run", "session_id": "todo-session",
                "workspace_key": "project:p1", "project_path": temp, "prompt": "创建教程",
                "mode": "agent", "permission": "safe", "todo_mode": True, "offline": True,
            })
            if service._task_thread:
                service._task_thread.join(3)
            self.assertTrue(service.store.get_run("todo-run")["config"]["todo_mode"])
            service.close()

    def test_recovery_snapshot_and_transient_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing), data_dir=Path(temp) / "data")
            service.store.ensure_session("recover-session")
            service.store.create_run("recover-run", "recover-session", "finish task", {"mode": "agent"})
            service.store.append_event({
                "type": "task_interrupted", "session_id": "recover-session", "request_id": "recover-run",
                "message": "network interrupted",
            })
            service.handle({"command": "get_recovery", "request_id": "snapshot"})
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            snapshot = next(event for event in events if event["type"] == "recovery_snapshot")
            self.assertEqual(snapshot["runs"][0]["request_id"], "recover-run")
            self.assertTrue(service._is_transient_failure(TimeoutError("provider timed out")))
            self.assertFalse(service._is_transient_failure(ValueError("invalid tool arguments")))
            service.handle({"command": "dismiss_recovery", "request_id": "dismiss", "target_request_id": "recover-run"})
            self.assertEqual(service.store.list_recoverable_runs(), [])
            service.close()

    def test_plan_mode_emits_plan_and_rejects_invalid_permission(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing))
            service.handle(
                {
                    "command": "start_task",
                    "request_id": "plan-1",
                    "project_path": temp,
                    "prompt": "先做一个计划",
                    "mode": "plan",
                    "permission": "safe",
                }
            )
            if service._task_thread:
                service._task_thread.join(3)
            service.handle(
                {
                    "command": "start_task",
                    "request_id": "bad-1",
                    "project_path": temp,
                    "prompt": "test",
                    "mode": "agent",
                    "permission": "root",
                }
            )
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            self.assertTrue(any(event["type"] == "plan_created" for event in events))
            self.assertTrue(any(event.get("code") == "invalid_permission" for event in events))
            service.close()

    def test_offline_plan_can_be_approved_and_reaches_completed_state(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing), data_dir=Path(temp) / "data")
            service.handle({
                "command": "start_task", "request_id": "plan-create", "session_id": "plan-session",
                "workspace_key": "project:p1", "project_path": temp, "prompt": "增加一个功能",
                "mode": "plan", "permission": "approval", "offline": True,
            })
            if service._task_thread:
                service._task_thread.join(3)
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            created = next(event for event in events if event["type"] == "plan_created")
            service.handle({
                "command": "plan_response", "request_id": "plan-approve", "session_id": "plan-session",
                "workspace_key": "project:p1", "plan_id": created["id"], "choice": "approve",
            })
            if service._task_thread:
                service._task_thread.join(3)
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            states = [event.get("state") for event in events if event["type"] == "plan_state_changed"]
            self.assertIn("waiting_for_review", states)
            self.assertIn("executing", states)
            self.assertIn("verifying", states)
            self.assertIn("completed", states)
            self.assertEqual(service.store.get_plan(created["id"])["state"], "completed")
            service.close()

    def test_offline_plan_revision_creates_second_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing), data_dir=Path(temp) / "data")
            service.handle({
                "command": "start_task", "request_id": "plan-create", "session_id": "revise-session",
                "workspace_key": "project:p1", "project_path": temp, "prompt": "原始目标",
                "mode": "plan", "permission": "safe", "offline": True,
            })
            if service._task_thread:
                service._task_thread.join(3)
            first = service.store.get_latest_plan("revise-session")
            service.handle({
                "command": "plan_response", "request_id": "plan-revise", "session_id": "revise-session",
                "workspace_key": "project:p1", "plan_id": first["id"], "choice": "revise",
                "feedback": "把验证拆得更清楚",
            })
            if service._task_thread:
                service._task_thread.join(3)
            revised = service.store.get_latest_plan("revise-session")
            self.assertEqual(revised["revision"], 2)
            self.assertEqual(revised["request"], "原始目标")
            self.assertEqual(revised["state"], "waiting_for_review")
            service.close()

    def test_cancel_command_notifies_immediately(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing))
            service.handle(
                {
                    "command": "start_task",
                    "request_id": "cancel-me",
                    "project_path": temp,
                    "prompt": "检查项目",
                    "mode": "agent",
                    "permission": "safe",
                    "offline": True,
                }
            )
            service.handle({"command": "cancel_task", "request_id": "cancel-command"})
            if service._task_thread:
                service._task_thread.join(2)
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            cancelled = [event for event in events if event["type"] == "task_cancelled"]
            self.assertEqual(len(cancelled), 1)
            self.assertEqual(cancelled[0]["request_id"], "cancel-me")
            service.close()

    def test_settings_tools_and_approval_protocol(self):
        outgoing = io.StringIO()
        service = SidecarService(JsonlWriter(outgoing))
        service.handle({"command": "get_settings", "request_id": "settings-1"})
        service.handle({"command": "get_tools", "request_id": "tools-1"})
        service.handle({"command": "get_skills", "request_id": "skills-1"})
        result = []
        worker = threading.Thread(
            target=lambda: result.append(service._request_approval(
                "set_working_directory", {"path": "D:\\work"},
                type("Decision", (), {"risk": type("Risk", (), {"name": "HIGH"})(), "reason": "changes directory"})(),
                "lead",
            ))
        )
        worker.start()
        deadline = time.monotonic() + 2
        approval_id = ""
        while time.monotonic() < deadline:
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            request = next((event for event in events if event["type"] == "approval_required"), None)
            if request:
                approval_id = request["approval_id"]
                break
            time.sleep(0.01)
        self.assertTrue(approval_id)
        service.handle({"command": "approval_response", "request_id": "answer-1", "approval_id": approval_id, "choice": "always"})
        worker.join(2)
        self.assertEqual(result, ["a"])
        cached = service._request_approval(
            "set_working_directory", {"path": "D:\\other"},
            type("Decision", (), {"risk": type("Risk", (), {"name": "HIGH"})(), "reason": "changes directory"})(),
            "lead",
        )
        self.assertEqual(cached, "y")
        events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertTrue(any(event["type"] == "settings_snapshot" for event in events))
        tools = next(event for event in events if event["type"] == "tools_snapshot")
        self.assertTrue(any(tool["name"] == "set_working_directory" for tool in tools["tools"]))
        skills = next(event for event in events if event["type"] == "skills_snapshot")
        self.assertTrue(any(skill["name"] == "code-review" for skill in skills["skills"]))
        service.close()


if __name__ == "__main__":
    unittest.main()
