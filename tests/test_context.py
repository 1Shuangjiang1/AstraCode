import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent_harness.context import COMPACT_MARKER, ContextManager, ContextPolicy


class ContextManagerTests(unittest.TestCase):
    def test_old_large_tool_result_is_recoverable_and_descriptive(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ContextManager(Path(temp), ContextPolicy(
                input_budget=100_000, keep_recent_tool_results=1,
                compact_tool_result_above=40, preview_head=18, preview_tail=12,
            ))
            raw = "first line\n" + "x" * 5_000 + "\nlast line"
            messages = [
                {"role": "assistant", "content": [SimpleNamespace(
                    type="tool_use", id="call-1", name="read_file", input={"path": "large.py"})]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": raw}]},
                {"role": "assistant", "content": [SimpleNamespace(
                    type="tool_use", id="call-2", name="path_exists", input={"path": "large.py"})]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-2", "content": "true"}]},
            ]
            report, should_summarize = manager.prepare("system", messages, [])
            compacted = messages[1]["content"][0]["content"]
            self.assertTrue(compacted.startswith(COMPACT_MARKER))
            self.assertIn('tool="read_file"', compacted)
            self.assertIn('"path": "large.py"', compacted)
            self.assertEqual(report.compacted_results, 1)
            self.assertGreater(report.saved_tokens, 0)
            self.assertFalse(should_summarize)
            self.assertEqual(Path(report.artifacts[0]).read_text(encoding="utf-8"), raw)

    def test_budget_counts_system_tools_and_output_reserve(self):
        manager = ContextManager(Path("."), ContextPolicy(input_budget=20, output_reserve=10))
        report, should_summarize = manager.prepare(
            "system instructions", [{"role": "user", "content": "hello"}],
            [{"name": "read_file", "description": "read"}],
        )
        self.assertEqual(report.request_tokens,
                         report.message_tokens + report.system_tokens + report.tool_schema_tokens + 10)
        self.assertTrue(should_summarize)


if __name__ == "__main__":
    unittest.main()
