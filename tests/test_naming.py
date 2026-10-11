import unittest
import json

from agent_harness.naming import clean_title, fallback_title, generate_title


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class ConversationNamingTests(unittest.TestCase):
    def test_cleans_markdown_quotes_and_labels(self):
        self.assertEqual(clean_title("## 标题：Python 文件工具开发。", "fallback"), "Python 文件工具开发")
        self.assertEqual(clean_title("“修复 Agent 超时”", "fallback"), "修复 Agent 超时")

    def test_fallback_is_short_and_stable(self):
        title = fallback_title("  请帮我开发一个支持日志查看的调试模式，并完成测试。  ")
        self.assertLessEqual(len(title), 24)
        self.assertTrue(title.startswith("请帮我开发"))

    def test_model_title_uses_tiny_non_tool_request(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": "工具消息中断恢复"}}]})

        title = generate_title(
            "secret", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V4-Flash",
            "修复 tool_use 没有 tool_result 的错误", opener=opener,
        )
        self.assertEqual(title, "工具消息中断恢复")
        self.assertEqual(captured["url"], "https://api.siliconflow.cn/v1/chat/completions")
        self.assertEqual(captured["payload"]["max_tokens"], 48)
        self.assertFalse(captured["payload"]["enable_thinking"])
        self.assertNotIn("tools", captured["payload"])


if __name__ == "__main__":
    unittest.main()
