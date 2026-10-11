"""Validate model-produced tool inputs before permission checks and execution."""

from __future__ import annotations

from typing import Any

from .schemas import TEAMMATE_TOOLS, TOOLS


TOOL_SCHEMAS = {tool["name"]: tool.get("input_schema", {}) for tool in TOOLS + TEAMMATE_TOOLS}


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def validate_tool_input(tool_name: str, args: Any) -> str | None:
    """Return a concise error for malformed model tool input, otherwise ``None``."""

    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        return f"unknown tool '{tool_name}'"
    if not isinstance(args, dict):
        return f"input must be an object, got {type(args).__name__}"

    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    missing = [name for name in required if name not in args]
    if missing:
        return "missing required field(s): " + ", ".join(missing)

    unexpected = sorted(set(args) - set(properties))
    if unexpected:
        return "unexpected field(s): " + ", ".join(unexpected)

    for name, value in args.items():
        expected = str((properties.get(name) or {}).get("type") or "")
        if expected and not _matches_type(value, expected):
            return f"field '{name}' must be {expected}, got {type(value).__name__}"
        if name in required and expected == "string" and not value.strip():
            return f"field '{name}' must not be empty"
    return None

