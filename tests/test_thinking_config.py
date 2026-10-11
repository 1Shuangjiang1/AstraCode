import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_harness.settings import create_client
from tests.helpers import make_settings


class _RecordingMessages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return "ok"


class _RecordingAnthropic:
    def __init__(self, **_kwargs):
        self.messages = _RecordingMessages()


class ThinkingConfigTests(unittest.TestCase):
    def test_high_effort_is_injected_into_every_real_request(self):
        with tempfile.TemporaryDirectory() as temp, patch("anthropic.Anthropic", _RecordingAnthropic):
            client = create_client(make_settings(Path(temp), fake_client=False))
            client.messages.create(model="deepseek-v4-flash", messages=[], max_tokens=10)
            self.assertEqual(client._client.messages.kwargs["thinking"], {"type": "enabled"})
            self.assertEqual(client._client.messages.kwargs["output_config"], {"effort": "high"})

    def test_disabled_thinking_does_not_send_effort(self):
        with tempfile.TemporaryDirectory() as temp, patch("anthropic.Anthropic", _RecordingAnthropic):
            settings = make_settings(Path(temp), fake_client=False, thinking_enabled=False, reasoning_effort="max")
            client = create_client(settings)
            client.messages.create(model="deepseek-v4-flash", messages=[], max_tokens=10)
            self.assertEqual(client._client.messages.kwargs["thinking"], {"type": "disabled"})
            self.assertNotIn("output_config", client._client.messages.kwargs)


if __name__ == "__main__":
    unittest.main()
