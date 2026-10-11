import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.fake_client import FakeAnthropic
from agent_harness.session_store import SessionStore
from agent_harness.sidecar import JsonlWriter, SidecarService
from tests.helpers import make_settings


class SessionStoreTests(unittest.TestCase):
    def test_first_user_message_can_be_replaced_by_generated_title(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "data")
            store.ensure_session("named-session")
            store.append_message("named-session", "user", "帮我修复工具调用协议并运行测试", message_id="first-user")
            self.assertTrue(store.should_generate_title("named-session"))
            self.assertTrue(store.update_session_title("named-session", "修复工具调用协议"))
            session = next(item for item in store.list_library()["conversations"] if item["id"] == "named-session")
            self.assertEqual(session["title"], "修复工具调用协议")
            store.append_message("named-session", "user", "继续", message_id="second-user")
            self.assertFalse(store.should_generate_title("named-session"))
            store.close()

    def test_each_request_gets_an_independent_jsonl_run_log(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "data")
            store.ensure_session("session-one")
            first = {"type": "user_message", "timestamp": "2026-08-07T00:00:00Z", "session_id": "session-one", "request_id": "request-a", "content": "hello"}
            second = {"type": "model_call_completed", "timestamp": "2026-08-07T00:00:01Z", "session_id": "session-one", "request_id": "request-a", "stop_reason": "end_turn"}
            store.append_event(first)
            store.append_event(second)
            path = store.run_log_path("session-one", "request-a")
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([item["type"] for item in events], ["user_message", "model_call_completed"])
            self.assertFalse(store.run_log_path("session-one", "request-b").exists())
            store.close()

    def test_incomplete_event_is_persisted_as_error_not_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "data")
            store.ensure_session("unfinished", status="running")
            store.append_event({
                "type": "task_incomplete", "timestamp": "2026-08-07T00:00:00Z",
                "session_id": "unfinished", "message": "requested file was not written",
            })
            conversation = store.list_library()["conversations"][0]
            self.assertEqual(conversation["status"], "error")
            store.close()

    def test_reopen_marks_abandoned_running_session_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            store = SessionStore(data)
            store.ensure_session("abandoned", status="running")
            store.close()
            reopened = SessionStore(data)
            self.assertEqual(reopened.list_library()["conversations"][0]["status"], "interrupted")
            reopened.close()

    def test_sidecar_library_protocol_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            outgoing = io.StringIO()
            service = SidecarService(JsonlWriter(outgoing), data_dir=Path(temp) / "data")
            service.handle({
                "command": "save_library", "request_id": "save-1",
                "projects": [{"id": "p1", "name": "项目", "path": str(Path(temp) / "project")}],
                "conversations": [{
                    "id": "s1", "workspaceKey": "project:p1", "title": "会话", "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-01T00:00:00Z", "status": "idle", "schemaVersion": 1,
                    "pinned": False, "archived": False, "messages": [], "timeline": [],
                }],
            })
            service.handle({"command": "set_session_state", "request_id": "pin-1", "session_id": "s1", "pinned": True})
            service.handle({"command": "get_library", "request_id": "list-1"})
            events = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            snapshot = next(event for event in events if event["type"] == "library_snapshot")
            self.assertTrue(snapshot["conversations"][0]["pinned"])
            service.close()

    def test_library_model_context_events_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = SessionStore(root / "data")
            project = {"id": "project-1", "name": "demo", "path": str(root / "project")}
            conversation = {
                "id": "session-1", "workspaceKey": "project:project-1", "title": "实现功能",
                "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:01:00Z",
                "schemaVersion": 1, "status": "completed", "pinned": True, "archived": False,
                "messages": [
                    {"id": "m1", "role": "user", "content": "开始", "timestamp": "2026-01-01T00:00:00Z"},
                    {"id": "m2", "role": "assistant", "content": "完成", "timestamp": "2026-01-01T00:01:00Z"},
                ],
                "timeline": [{"type": "task_completed", "timestamp": "2026-01-01T00:01:00Z", "uiId": "e1"}],
                "todos": [{"content": "verify", "status": "completed"}],
                "agents": [{"id": "subagent:1", "kind": "subagent", "name": "Explore", "events": []}],
            }
            store.save_library([project], [conversation])
            store.append_event({"type": "tool_completed", "timestamp": "2026-01-01T00:00:30Z", "session_id": "session-1", "tool": "write_file"})
            model_history = [
                {"role": "user", "content": "开始"},
                {"role": "assistant", "content": [{"type": "text", "text": "完成"}]},
            ]
            store.save_model_state("session-1", model_history, {"summary": "完成了基础实现"})

            library = store.list_library()
            self.assertEqual(library["projects"][0]["name"], "demo")
            self.assertTrue(library["conversations"][0]["pinned"])
            self.assertEqual(library["conversations"][0]["messages"][1]["content"], "完成")
            self.assertEqual(library["conversations"][0]["todos"][0]["content"], "verify")
            self.assertEqual(library["conversations"][0]["agents"][0]["name"], "Explore")
            loaded_history, loaded_summary = store.load_model_state("session-1")
            self.assertEqual(loaded_history[1]["content"][0]["text"], "完成")
            self.assertEqual(loaded_summary["summary"], "完成了基础实现")
            event_file = root / "data" / "sessions" / "session-1" / "events.jsonl"
            self.assertEqual(json.loads(event_file.read_text(encoding="utf-8"))["tool"], "write_file")

            self.assertTrue(store.update_session_state("session-1", archived=True, pinned=False))
            self.assertTrue(store.list_library()["conversations"][0]["archived"])
            self.assertTrue(store.delete_session("session-1"))
            self.assertEqual(store.list_library()["conversations"], [])
            self.assertFalse(event_file.exists())
            store.close()

    def test_run_checkpoint_and_recovery_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "data")
            store.ensure_session("session-run")
            store.create_run("run-1", "session-run", "implement feature", {"verification": "strict"})
            store.append_event({"type": "session_started", "timestamp": "2026-01-01T00:00:00Z", "session_id": "session-run", "request_id": "run-1"})
            store.append_event({"type": "tool_started", "timestamp": "2026-01-01T00:00:01Z", "session_id": "session-run", "request_id": "run-1", "tool_id": "t1", "tool": "write_file", "detail": "a.py"})
            current = store.get_run("run-1")
            self.assertEqual(current["state"], "running")
            self.assertEqual(current["checkpoint"]["pending_tool"]["tool"], "write_file")
            store.close()
            reopened = SessionStore(Path(temp) / "data")
            recovered = reopened.list_recoverable_runs()
            self.assertEqual(recovered[0]["state"], "interrupted")
            self.assertEqual(recovered[0]["checkpoint"]["pending_tool"]["tool"], "write_file")
            reopened.clear_recovery("run-1")
            self.assertEqual(reopened.list_recoverable_runs(), [])
            reopened.close()

    def test_compaction_keeps_recent_turn_and_emits_structured_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_text("目标、关键文件和下一步的连续性摘要")
            snapshots = []
            app = AgentApp(make_settings(Path(temp)), client, compaction_callback=snapshots.append)
            messages = []
            for index in range(9):
                messages.extend([
                    {"role": "user", "content": f"第 {index} 个请求"},
                    {"role": "assistant", "content": [{"type": "text", "text": f"第 {index} 个回复"}]},
                ])
            compacted = app.auto_compact(messages)
            self.assertIn("conversation-summary", compacted[0]["content"])
            self.assertIn("第 3 个请求", compacted[0]["content"])
            self.assertEqual(compacted[-1]["content"][0]["text"], "第 8 个回复")
            self.assertEqual(snapshots[0]["summary"], "目标、关键文件和下一步的连续性摘要")
            self.assertLess(snapshots[0]["compactedMessages"], snapshots[0]["originalMessages"])


if __name__ == "__main__":
    unittest.main()
