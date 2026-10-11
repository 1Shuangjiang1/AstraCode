import tempfile
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.fake_client import FakeAnthropic
from tests.helpers import make_settings


class AgentPermissionReuseTests(unittest.TestCase):
    def test_subagent_uses_shared_permission_engine(self):
        prompts = []
        def deny(tool, args, decision, actor):
            prompts.append(actor)
            return "n"
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("bash", {"command": "rm important.txt"})
            client.messages.enqueue_text("could not delete")
            events = []
            app = AgentApp(make_settings(Path(temp)), client, deny, trace_callback=events.append)
            result = app.subagents.run("remove it", "Explore")
            self.assertEqual(result, "could not delete")
            self.assertTrue(prompts[0].startswith("subagent:"))
            tool_results = client.messages.calls[1]["messages"][-1]["content"]
            self.assertIn("Permission denied", tool_results[0]["content"])
            self.assertTrue(any(event.get("type") == "agent_started" for event in events))
            self.assertTrue(any(event.get("type") == "agent_tool_completed" for event in events))
            self.assertTrue(any(event.get("type") == "agent_completed" for event in events))

    def test_teammate_uses_shared_permission_engine(self):
        prompts = []
        def deny(tool, args, decision, actor):
            prompts.append(actor)
            return "n"
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("bash", {"command": "rm teammate.txt"})
            client.messages.enqueue_text("finished")
            events = []
            app = AgentApp(make_settings(Path(temp)), client, deny, trace_callback=events.append)
            app.team.spawn("worker", "tester", "try delete")
            app.team.threads["worker"].join(timeout=3)
            self.assertFalse(app.team.threads["worker"].is_alive())
            self.assertIn("teammate:worker", prompts)
            self.assertTrue(any(event.get("type") == "agent_started" and event.get("agent_kind") == "teammate" for event in events))
            self.assertTrue(any(event.get("type") == "agent_tool_completed" for event in events))
            self.assertTrue(any(event.get("type") == "agent_completed" for event in events))


if __name__ == "__main__":
    unittest.main()
