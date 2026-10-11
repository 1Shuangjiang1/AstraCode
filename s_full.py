#!/usr/bin/env python3
"""CLI entry point for the modular s_full agent harness.

The pre-refactor implementation is preserved in
legacy/s_full_monolith_2026-08-05.py.
"""

from agent_harness.app import AgentApp, create_app
from agent_harness.fake_client import FakeAnthropic
from agent_harness.schemas import TOOLS


APP = create_app()
MODEL = APP.settings.model
WORKDIR = APP.settings.workdir
client = APP.client

# Compatibility aliases for existing notebooks and scripts.
TODO = APP.todo
SKILLS = APP.skills
TASK_MGR = APP.tasks
BG = APP.background
BUS = APP.bus
TEAM = APP.team
TOOL_HANDLERS = APP.handlers


def agent_loop(messages: list, max_rounds: int | None = None, max_seconds: float | None = None):
    return APP.agent_loop(messages, max_rounds, max_seconds)


def run_bash(command: str) -> str:
    return APP.execute_tool("bash", {"command": command})


def run_read(path: str, limit: int | None = None) -> str:
    return APP.execute_tool("read_file", {"path": path, "limit": limit})


def run_write(path: str, content: str) -> str:
    return APP.execute_tool("write_file", {"path": path, "content": content})


def run_edit(path: str, old_text: str, new_text: str) -> str:
    return APP.execute_tool("edit_file", {"path": path, "old_text": old_text, "new_text": new_text})


if __name__ == "__main__":
    APP.repl()

