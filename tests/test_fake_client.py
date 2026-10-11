import tempfile
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.fake_client import FakeAnthropic
from tests.helpers import make_settings


class FakeClientTests(unittest.TestCase):
    def test_offline_agent_loop_can_call_tool_and_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("write_file", {"path": "result.txt", "content": "offline ok"})
            client.messages.enqueue_text("done")
            app = AgentApp(make_settings(Path(temp)), client)
            messages = [{"role": "user", "content": "write a result"}]
            status = app.agent_loop(messages)
            self.assertEqual(status, "completed")
            self.assertEqual((Path(temp) / "result.txt").read_text(encoding="utf-8"), "offline ok")
            self.assertGreaterEqual(len(client.messages.calls), 3)  # tool, final answer, memory extraction

    def test_fake_default_response_needs_no_script(self):
        client = FakeAnthropic()
        response = client.messages.create(messages=[{"role": "user", "content": "hello"}])
        self.assertEqual(response.stop_reason, "end_turn")
        self.assertIn("Offline", response.content[0].text)


if __name__ == "__main__":
    unittest.main()

