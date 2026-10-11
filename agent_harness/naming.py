"""Low-cost conversation title generation with a deterministic fallback."""

from __future__ import annotations

import re
import json
from typing import Any, Callable
from urllib.request import Request, urlopen


TITLE_SYSTEM = (
    "你是编程助手的对话命名器。根据用户第一条请求生成一个简短、具体、可检索的中文标题。"
    "只输出标题本身，不要解释，不要引号，不要 Markdown，不要句号。标题控制在 6 到 16 个汉字；"
    "必要时可以保留 Python、API、UI 等技术词。"
)


def fallback_title(prompt: str, limit: int = 24) -> str:
    text = re.sub(r"\s+", " ", str(prompt or "")).strip()
    text = re.sub(r"^[#>*\-\d.、\s]+", "", text)
    text = text.strip("“”\"'`。，！？!?：:；; ")
    return (text[:limit].rstrip("，。；：、 ") or "新对话")


def clean_title(value: str, prompt: str) -> str:
    first = str(value or "").strip().splitlines()[0] if str(value or "").strip() else ""
    first = re.sub(r"^#{1,6}\s*", "", first)
    first = re.sub(r"^(?:标题|对话标题)\s*[:：]\s*", "", first, flags=re.IGNORECASE)
    first = first.strip("“”\"'`* _。，！？!?：:；;|-—")
    first = re.sub(r"\s+", " ", first)
    if not first or len(first) > 30:
        return fallback_title(prompt)
    return first


def _chat_completions_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("命名模型 Base URL 不能为空")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def generate_title(
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    *,
    timeout: float = 45,
    opener: Callable[..., Any] = urlopen,
) -> str:
    """Generate a title through SiliconFlow's OpenAI-compatible endpoint.

    This intentionally has no dependency on the main Anthropic-compatible
    client so a naming outage or configuration change cannot alter agent calls.
    """
    if not str(api_key or "").strip():
        raise ValueError("未配置命名模型 API Key")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": TITLE_SYSTEM},
            {"role": "user", "content": str(prompt)[:4000]},
        ],
        "stream": False,
        "enable_thinking": False,
        "max_tokens": 48,
        "temperature": 0.2,
    }
    request = Request(
        _chat_completions_url(base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with opener(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    choices = result.get("choices") or []
    if not choices:
        raise ValueError("命名模型没有返回 choices")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("命名模型返回了空标题")
    return clean_title(content, prompt)
