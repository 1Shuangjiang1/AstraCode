import tempfile
import unittest
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.completion import CompletionGate, forbids_filesystem_mutation, requests_filesystem_mutation, task_contract
from agent_harness.fake_client import FakeAnthropic
from tests.helpers import make_settings


class CompletionGateTests(unittest.TestCase):
    def test_detects_reported_chinese_document_request(self):
        request = "在这个文档里，写一个全新的md文档，名为算法题目思路"
        self.assertTrue(requests_filesystem_mutation(request))
        self.assertFalse(requests_filesystem_mutation("解释一下哈希表的工作原理"))

    def test_runtime_todo_directive_cannot_turn_write_request_read_only(self):
        request = (
            "<execution-requirements>TodoWrite 不能代替 write_file、edit_file、bash 等实际工具。"
            "</execution-requirements>\n\n用户任务：\n"
            "能否在这个文档里面写一个算法教程，包括双指针经典题目，使用 Python"
        )
        gate = CompletionGate(request)
        self.assertEqual(gate.required_evidence, ["mutation"])
        self.assertFalse(forbids_filesystem_mutation(request))
        self.assertFalse(gate.tool_forbidden("write_file", {"path": "tutorial.md"}))

    def test_premature_progress_message_is_forced_to_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("list_directory", {"path": "."})
            client.messages.enqueue_text("现在我来编写这份文档。")
            client.messages.enqueue_tool(
                "write_file", {"path": "算法题目思路.md", "content": "# 算法题目思路\n"},
            )
            client.messages.enqueue_text("文档已创建。")
            app = AgentApp(make_settings(Path(temp)), client)
            messages = [{"role": "user", "content": "写一个全新的md文档，名为算法题目思路"}]

            status = app.agent_loop(messages, finalize_memory=False)

            self.assertEqual(status, "completed")
            self.assertTrue((Path(temp) / "算法题目思路.md").exists())
            self.assertTrue(any(
                isinstance(item.get("content"), str) and item["content"].startswith("<completion-guard")
                for item in messages
            ))

    def test_repeated_non_action_returns_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_text("我先看看。")
            client.messages.enqueue_text("现在开始写。")
            client.messages.enqueue_text("接下来创建文件。")
            app = AgentApp(make_settings(Path(temp)), client)
            messages = [{"role": "user", "content": "创建一个 README 文档"}]

            status = app.agent_loop(messages, finalize_memory=False)

            self.assertEqual(status, "incomplete")

    def test_explanation_can_finish_without_mutation(self):
        gate = CompletionGate("解释一下链表的快慢指针")
        decision = gate.evaluate("end_turn", "这里是原理说明。")
        self.assertEqual(decision.action, "complete")

    def test_action_contracts_require_matching_successful_tools(self):
        self.assertEqual(task_contract("检查这个项目的代码"), ["inspection"])
        self.assertEqual(task_contract("请运行测试并修复代码"), ["mutation", "command"])
        gate = CompletionGate("请运行测试并修复代码")
        gate.record_tool_result("write_file", "Wrote 4 bytes")
        decision = gate.evaluate("end_turn", "修复完成。")
        self.assertEqual(decision.missing_evidence, ("command",))
        gate.record_tool_result("bash", "3 passed")
        self.assertEqual(gate.evaluate("end_turn", "修复并测试完成。").action, "complete")

    def test_successful_shell_write_counts_as_mutation_evidence(self):
        gate = CompletionGate("创建一个 result.txt 文件")
        gate.record_tool_result("bash", "completed", {"command": "Set-Content result.txt ok"})
        self.assertEqual(gate.evaluate("end_turn", "文件已创建。").action, "complete")

    def test_todo_mode_enforces_initialization_and_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("write_file", {"path": "tutorial.md", "content": "blocked"})
            initial = [
                {"content": "确认目标", "status": "in_progress", "activeForm": "正在确认目标"},
                {"content": "编写教程", "status": "pending", "activeForm": "正在编写教程"},
                {"content": "检查结果", "status": "pending", "activeForm": "正在检查结果"},
            ]
            completed = [{**item, "status": "completed"} for item in initial]
            client.messages.enqueue_tool("TodoWrite", {"items": initial})
            client.messages.enqueue_tool("write_file", {"path": "tutorial.md", "content": "# 双指针\n"})
            client.messages.enqueue_text("教程已经写好。")
            client.messages.enqueue_tool("TodoWrite", {"items": completed})
            client.messages.enqueue_text("教程已经写好并检查完成。")
            traces = []
            app = AgentApp(make_settings(Path(temp), max_rounds=8), client, trace_callback=traces.append, require_todo=True)
            messages = [{"role": "user", "content": "创建双指针教程文档"}]

            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "completed")
            self.assertEqual((Path(temp) / "tutorial.md").read_text(encoding="utf-8"), "# 双指针\n")
            self.assertTrue(any(item.get("type") == "tool_blocked_by_todo_contract" for item in traces))
            self.assertTrue(any(item.get("type") == "todo_completion_blocked" for item in traces))

    def test_todo_mode_rejects_invalid_one_item_checklist(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("TodoWrite", {"items": [
                {"content": "全部完成", "status": "in_progress", "activeForm": "正在全部完成"},
            ]})
            client.messages.enqueue_text("完成。")
            app = AgentApp(make_settings(Path(temp), max_rounds=2), client, require_todo=True)
            status = app.agent_loop([{"role": "user", "content": "创建文档"}], finalize_memory=False)
            self.assertNotEqual(status, "completed")
            self.assertFalse(app.todo.has_items())

    def test_negated_actions_never_create_positive_evidence_requirements(self):
        request = "检查这个项目目录里有哪些文件，不要修改任何内容，然后告诉我结果。"
        self.assertEqual(task_contract(request), ["inspection"])
        self.assertFalse(requests_filesystem_mutation(request))
        self.assertTrue(forbids_filesystem_mutation(request))
        self.assertEqual(task_contract("Review the project without modifying any files."), ["inspection"])
        self.assertEqual(task_contract("请不要运行测试，只读取日志文件。"), ["inspection"])

    def test_non_file_tasks_and_scoped_read_only_are_not_global_file_contracts(self):
        self.assertEqual(task_contract("不要修改项目文件，创建两个持久任务并查看列表"), [])
        self.assertEqual(task_contract(
            "不要修改项目文件。创建两个持久任务，主题为检查计算模块和整理结论。"
        ), [])
        request = (
            "让子 agent 只读审查 parser.py，然后由主 agent 创建 report.md 并写入结论。"
            "不要让子 agent 修改文件。"
        )
        self.assertEqual(task_contract(request), ["mutation", "delegation"])
        self.assertFalse(forbids_filesystem_mutation(request))

    def test_delegated_mutation_can_be_verified_without_lead_write(self):
        request = "主 agent 不得亲自写文件，启动 teammate 创建 result.txt，然后检查并读取文件。"
        gate = CompletionGate(request)
        self.assertTrue(forbids_filesystem_mutation(request))
        self.assertTrue(gate.tool_forbidden("write_file", {"path": "result.txt", "content": "x"}))
        self.assertTrue(gate.tool_forbidden("bash", {"command": "Set-Content result.txt x"}))
        gate.record_tool_result("spawn_teammate", "Spawned")
        gate.record_tool_result("path_exists", "true")
        self.assertEqual(gate.evaluate("end_turn", "队友已创建并验证文件，摘要如下。 ").action, "complete")

    def test_read_only_contract_blocks_model_write_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_tool("write_file", {"path": "forbidden.txt", "content": "no"})
            client.messages.enqueue_tool("list_directory", {"path": "."})
            client.messages.enqueue_text("目录检查完成，没有修改文件。")
            traces = []
            app = AgentApp(make_settings(Path(temp)), client, trace_callback=traces.append)
            messages = [{"role": "user", "content": "检查这个项目，不要修改任何文件。"}]
            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "completed")
            self.assertFalse((Path(temp) / "forbidden.txt").exists())
            self.assertTrue(any(item.get("type") == "tool_blocked_by_task_contract" for item in traces))

    def test_protocol_stop_reasons_are_not_all_completion(self):
        gate = CompletionGate("解释一下链表")
        self.assertEqual(gate.evaluate("max_tokens", "截断内容").action, "continue")
        self.assertEqual(gate.evaluate("pause_turn", "").action, "continue")
        self.assertEqual(gate.evaluate("refusal", "无法回答").action, "refused")
        self.assertEqual(gate.evaluate("stop_sequence", "部分内容").action, "incomplete")
        self.assertEqual(gate.evaluate("stop", "完整回答").action, "complete")

    def test_truncated_response_gets_a_continuation_turn(self):
        with tempfile.TemporaryDirectory() as temp:
            client = FakeAnthropic()
            client.messages.enqueue_text("前半部分", "max_tokens")
            client.messages.enqueue_text("完整回答")
            traces = []
            app = AgentApp(make_settings(Path(temp)), client, trace_callback=traces.append)
            messages = [{"role": "user", "content": "解释哈希表"}]

            self.assertEqual(app.agent_loop(messages, finalize_memory=False), "completed")
            self.assertTrue(any(
                isinstance(item.get("content"), str) and item["content"].startswith("<completion-guard")
                for item in messages
            ))
            reasons = [item.get("reason") for item in traces if item.get("type") == "completion_evaluated"]
            self.assertEqual(reasons, ["provider_output_truncated", "contract_satisfied"])


if __name__ == "__main__":
    unittest.main()
