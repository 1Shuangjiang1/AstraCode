import unittest
from types import SimpleNamespace

from agent_harness.ui import text_content


class ResponseContentTests(unittest.TestCase):
    def test_ignores_thinking_tools_and_null_text(self):
        content = [
            SimpleNamespace(type="thinking", thinking="private", text=None),
            SimpleNamespace(type="text", text=None),
            SimpleNamespace(type="tool_use", name="bash", text=None),
            SimpleNamespace(type="text", text="final answer"),
        ]
        self.assertEqual(text_content(content), "final answer")

    def test_supports_dict_blocks(self):
        self.assertEqual(text_content([
            {"type": "thinking", "thinking": "hidden"},
            {"type": "text", "text": "done"},
        ]), "done")


if __name__ == "__main__":
    unittest.main()
