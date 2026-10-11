import tempfile
import unittest
from pathlib import Path

from agent_harness.fake_client import FakeAnthropic
from agent_harness.verifier import Verifier


class VerifierTests(unittest.TestCase):
    def test_off_mode_does_not_call_model(self):
        client = FakeAnthropic()
        result = Verifier(client, "fake").verify(
            mode="off", request="write file", final_answer="done", change_set={}, tool_evidence=[])
        self.assertTrue(result.passed)
        self.assertEqual(client.messages.calls, [])

    def test_standard_parses_structured_result(self):
        client = FakeAnthropic()
        client.messages.enqueue_text('{"verdict":"pass","confidence":0.9,"summary":"ok","checks":[],"issues":[]}')
        result = Verifier(client, "fake").verify(
            mode="standard", request="write file", final_answer="done",
            change_set={"files": [{"path": "a.py", "status": "created"}]},
            tool_evidence=[{"tool": "write_file", "ok": True}],
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.summary, "ok")

    def test_strict_can_read_before_deciding(self):
        client = FakeAnthropic()
        client.messages.enqueue_tool("read_file", {"path": "a.py"})
        client.messages.enqueue_text('{"verdict":"needs_fix","confidence":0.8,"summary":"missing test","checks":[],"issues":[{"severity":"high","message":"no test"}]}')
        calls = []
        result = Verifier(client, "fake").verify(
            mode="strict", request="write code", final_answer="done",
            change_set={"files": [{"path": "a.py", "status": "created"}]}, tool_evidence=[],
            read_tool=lambda name, args: calls.append((name, args)) or "print('ok')",
        )
        self.assertEqual(calls[0][0], "read_file")
        self.assertEqual(result.verdict, "needs_fix")
        self.assertEqual(result.rounds, 2)


if __name__ == "__main__":
    unittest.main()
