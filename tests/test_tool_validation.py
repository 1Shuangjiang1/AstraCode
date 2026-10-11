import tempfile
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.fake_client import FakeAnthropic, FakeResponse, FakeToolUseBlock
from agent_harness.tool_validation import validate_tool_input
from tests.helpers import make_settings


class ToolValidationTests(unittest.TestCase):
    def test_required_and_unexpected_fields_are_rejected(self):
        self.assertEqual(
            validate_tool_input("write_file", {}),
            "missing required field(s): path, content",
        )
        self.assertIn("unexpected field(s): force", validate_tool_input(
            "delete_file", {"path": "a.txt", "force": True},
        ))
        self.assertIsNone(validate_tool_input(
            "write_file", {"path": "a.txt", "content": "ok"},
        ))

    def test_truncated_empty_tool_call_is_reported_then_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages._responses.append(FakeResponse([
                FakeToolUseBlock("write_file", {}, "truncated-call"),
            ], "max_tokens"))
            client.messages.enqueue_tool(
                "write_file", {"path": "tutorial.md", "content": "# Tutorial\n"}, "retry-call",
            )
            client.messages.enqueue_text("教程已经创建并验证。")
            traces = []
            app = AgentApp(make_settings(Path(temp)), client, trace_callback=traces.append)
            messages = [{"role": "user", "content": "创建 tutorial.md 教程"}]

            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "completed")
            self.assertEqual((Path(temp) / "tutorial.md").read_text(encoding="utf-8"), "# Tutorial\n")
            first_results = messages[2]["content"]
            self.assertIn("missing required field(s): path, content", first_results[0]["content"])
            self.assertEqual(first_results[1]["type"], "text")
            self.assertIn("truncated-response", first_results[1]["text"])


if __name__ == "__main__":
    unittest.main()
