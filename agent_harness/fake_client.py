"""Small Anthropic-compatible fake used by the REPL and unit tests."""

from __future__ import annotations

import itertools
import copy
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    name: str
    input: dict
    id: str
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"


class FakeMessages:
    def __init__(self):
        self._responses: list[FakeResponse] = []
        self.calls: list[dict] = []
        self._ids = itertools.count(1)

    def enqueue_text(self, text: str, stop_reason: str = "end_turn"):
        self._responses.append(FakeResponse([FakeTextBlock(text)], stop_reason))

    def enqueue_tool(self, name: str, tool_input: dict, tool_id: str | None = None):
        block = FakeToolUseBlock(name, tool_input, tool_id or f"fake_tool_{next(self._ids)}")
        self._responses.append(FakeResponse([block], "tool_use"))

    def create(self, **kwargs):
        # Keep an immutable-at-call-time history for assertions and debugging.
        self.calls.append(copy.deepcopy(kwargs))
        if self._responses:
            return self._responses.pop(0)
        prompt = kwargs.get("messages", [{}])[-1].get("content", "")
        if isinstance(prompt, str) and ("Return ONLY a JSON array" in prompt or "Return a JSON array" in prompt):
            return FakeResponse([FakeTextBlock("[]")])
        return FakeResponse([FakeTextBlock("[FAKE] Offline model response.")])


class FakeAnthropic:
    def __init__(self):
        self.messages = FakeMessages()
