import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.fake_client import FakeAnthropic
from agent_harness.planning import PlanRunner, READ_ONLY_PLAN_TOOLS, execution_prompt
from tests.helpers import make_settings


class PlanningTests(unittest.TestCase):
    def test_execution_prompt_drops_planning_only_request(self):
        prompt = execution_prompt({
            "request": "计划阶段不要修改文件",
            "steps": [{"description": "创建 feature.py"}],
        })
        self.assertNotIn("计划阶段不要修改文件", prompt)
        self.assertIn("创建 feature.py", prompt)

    def test_runner_exposes_only_read_only_tools_and_parses_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            client = FakeAnthropic()
            client.messages.enqueue_tool("read_file", {"path": "app.py"}, "read-1")
            client.messages.enqueue_text(json.dumps({
                "title": "调整入口",
                "summary": "根据真实入口完成修改。",
                "assumptions": ["保持当前运行方式"],
                "steps": [{
                    "title": "修改入口", "description": "更新 app.py",
                    "files": ["app.py"], "verification": "运行 app.py",
                }],
                "risks": ["输出行为变化"], "verification": ["运行现有测试"],
            }, ensure_ascii=False))
            app = AgentApp(make_settings(root), client)
            messages = [{"role": "user", "content": "调整入口"}]
            plan, markdown = PlanRunner(app).run(messages, "调整入口")
            sent_names = {tool["name"] for tool in client.messages.calls[0]["tools"]}
            self.assertEqual(sent_names, READ_ONLY_PLAN_TOOLS)
            self.assertNotIn("write_file", sent_names)
            self.assertEqual(plan["steps"][0]["files"], ["app.py"])
            self.assertEqual(plan["state"], "waiting_for_review")
            self.assertIn("计划已进入待审阅状态", markdown)

    def test_runner_forces_final_answer_after_tool_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("a", encoding="utf-8")
            client = FakeAnthropic()
            client.messages.enqueue_tool("read_file", {"path": "a.txt"}, "read-1")
            client.messages.enqueue_text('{"title":"收口计划","summary":"完成","steps":[{"title":"改动","description":"执行","files":["a.txt"],"verification":"检查"}],"risks":[],"verification":[]}')
            app = AgentApp(make_settings(root), client)
            plan, _ = PlanRunner(app).run([{"role": "user", "content": "任务"}], "任务", max_tool_calls=1)
            self.assertEqual(plan["title"], "收口计划")
            self.assertEqual(client.messages.calls[1]["tools"], [])
            self.assertIn("Inspection is now complete", client.messages.calls[1]["system"])


if __name__ == "__main__":
    unittest.main()
