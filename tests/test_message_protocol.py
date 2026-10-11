import tempfile
import threading
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.fake_client import FakeAnthropic, FakeResponse, FakeTextBlock, FakeToolUseBlock
from agent_harness.message_protocol import repair_tool_protocol
from agent_harness.session_store import SessionStore
from tests.helpers import make_settings


def tool_result_ids(message):
    return [
        block.get("tool_use_id") for block in message.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


class MessageProtocolTests(unittest.TestCase):
    def test_repairs_interrupted_tool_use_before_existing_user_prompt(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "write_file", "input": {}},
            ]},
            {"role": "user", "content": "下一条用户请求"},
        ]

        report = repair_tool_protocol(messages)

        self.assertTrue(report["changed"])
        self.assertEqual(tool_result_ids(messages[1]), ["call-1"])
        self.assertEqual(messages[1]["content"][1], {"type": "text", "text": "下一条用户请求"})

    def test_fills_partial_multi_tool_result_and_preserves_text(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "read_file", "input": {}},
                {"type": "tool_use", "id": "call-2", "name": "list_directory", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "ok"},
                {"type": "text", "text": "continue"},
            ]},
        ]

        report = repair_tool_protocol(messages)

        self.assertEqual(report["repaired_ids"], ["call-2"])
        self.assertEqual(tool_result_ids(messages[1]), ["call-1", "call-2"])
        self.assertEqual(messages[1]["content"][-1]["text"], "continue")

    def test_valid_history_is_unchanged(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-1", "name": "read_file", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "ok"},
            ]},
        ]
        self.assertFalse(repair_tool_protocol(messages)["changed"])

    def test_persistence_never_saves_an_orphan_tool_use(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "data")
            store.ensure_session("session-1")
            store.save_model_state("session-1", [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "call-1", "name": "write_file", "input": {}},
                ]},
            ])

            loaded, _ = store.load_model_state("session-1")
            self.assertEqual(tool_result_ids(loaded[1]), ["call-1"])
            store.close()

    def test_agent_self_heals_persisted_history_before_model_call(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_text("已继续并完成。")
            traces = []
            app = AgentApp(make_settings(Path(temp)), client, trace_callback=traces.append)
            messages = [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "old-call", "name": "write_file", "input": {}},
                ]},
                {"role": "user", "content": "继续任务"},
            ]

            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "completed")
            sent = client.messages.calls[0]["messages"]
            self.assertEqual(tool_result_ids(sent[1]), ["old-call"])
            self.assertTrue(any(item.get("type") == "message_protocol_repaired" for item in traces))

    def test_cancellation_records_results_for_every_tool_call(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages._responses.append(FakeResponse([
                FakeToolUseBlock("list_directory", {"path": "."}, "call-1"),
                FakeToolUseBlock("path_exists", {"path": "a.txt"}, "call-2"),
            ], "tool_use"))
            cancelled = threading.Event()
            app = AgentApp(make_settings(Path(temp)), client, cancel_event=cancelled)
            original_execute = app.execute_tool

            def cancel_after_first(name, args, actor="lead"):
                result = original_execute(name, args, actor)
                cancelled.set()
                return result

            app.execute_tool = cancel_after_first
            messages = [{"role": "user", "content": "检查目录"}]

            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "cancelled")
            self.assertEqual(tool_result_ids(messages[-1]), ["call-1", "call-2"])
            self.assertFalse(repair_tool_protocol(messages)["changed"])

    def test_tool_blocks_are_executed_even_with_nonstandard_stop_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages._responses.append(FakeResponse([
                FakeToolUseBlock("list_directory", {"path": "."}, "call-1"),
            ], "end_turn"))
            client.messages.enqueue_text("目录检查完成。")
            app = AgentApp(make_settings(Path(temp)), client)
            messages = [{"role": "user", "content": "检查目录"}]

            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "completed")
            self.assertEqual(tool_result_ids(messages[2]), ["call-1"])


if __name__ == "__main__":
    unittest.main()
