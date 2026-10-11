"""Repair Anthropic-compatible tool-use message chains before persistence/API calls."""

from __future__ import annotations

from typing import Any


INTERRUPTED_TOOL_RESULT = (
    "Error: Tool execution was interrupted before a result was recorded. "
    "Do not assume that this tool call changed or inspected the workspace."
)


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _blocks(message: dict[str, Any]) -> list[Any]:
    content = message.get("content")
    return content if isinstance(content, list) else []


def _tool_use_ids(message: dict[str, Any]) -> list[str]:
    if message.get("role") != "assistant":
        return []
    return [
        str(_value(block, "id"))
        for block in _blocks(message)
        if _value(block, "type") == "tool_use" and _value(block, "id")
    ]


def _text_block(content: Any) -> dict[str, str] | None:
    text = str(content or "")
    return {"type": "text", "text": text} if text else None


def repair_tool_protocol(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Make every assistant tool_use immediately followed by matching tool_result blocks.

    Interrupted runs commonly leave ``assistant(tool_use) -> user(new prompt)``. In that
    case the synthetic error result is prepended to the existing user prompt, preserving
    both role alternation and the user's new request.
    """

    repaired_ids: list[str] = []
    removed_orphans: list[str] = []
    inserted_messages = 0
    index = 0
    while index < len(messages):
        expected = _tool_use_ids(messages[index])
        if not expected:
            index += 1
            continue

        if index + 1 >= len(messages) or messages[index + 1].get("role") != "user":
            messages.insert(index + 1, {"role": "user", "content": []})
            inserted_messages += 1

        following = messages[index + 1]
        raw_content = following.get("content")
        if isinstance(raw_content, list):
            content = list(raw_content)
        else:
            text = _text_block(raw_content)
            content = [text] if text else []

        result_by_id: dict[str, Any] = {}
        non_results: list[Any] = []
        expected_set = set(expected)
        for block in content:
            if _value(block, "type") != "tool_result":
                non_results.append(block)
                continue
            tool_id = str(_value(block, "tool_use_id", ""))
            if tool_id in expected_set and tool_id not in result_by_id:
                result_by_id[tool_id] = block
            else:
                removed_orphans.append(tool_id or "<missing-id>")

        ordered_results: list[Any] = []
        for tool_id in expected:
            if tool_id in result_by_id:
                ordered_results.append(result_by_id[tool_id])
            else:
                ordered_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": INTERRUPTED_TOOL_RESULT,
                    "is_error": True,
                })
                repaired_ids.append(tool_id)
        following["content"] = ordered_results + non_results
        index += 2

    # Remove tool_result blocks that are not attached to the immediately preceding
    # assistant tool-use turn. These can also be left behind by manual history edits.
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") != "user" or not isinstance(message.get("content"), list):
            index += 1
            continue
        expected = set(_tool_use_ids(messages[index - 1])) if index else set()
        cleaned: list[Any] = []
        for block in message["content"]:
            if _value(block, "type") != "tool_result":
                cleaned.append(block)
                continue
            tool_id = str(_value(block, "tool_use_id", ""))
            if tool_id in expected:
                cleaned.append(block)
            else:
                removed_orphans.append(tool_id or "<missing-id>")
        message["content"] = cleaned
        if not cleaned:
            messages.pop(index)
            continue
        index += 1

    return {
        "changed": bool(repaired_ids or removed_orphans or inserted_messages),
        "repaired_ids": repaired_ids,
        "inserted_results": len(repaired_ids),
        "inserted_messages": inserted_messages,
        "removed_orphans": removed_orphans,
    }

