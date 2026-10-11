from pathlib import Path

from agent_harness.settings import Settings


def make_settings(workdir: Path, **overrides) -> Settings:
    values = dict(
        workdir=workdir.resolve(), model="deepseek-v4-flash", title_model="deepseek-ai/DeepSeek-V4-Flash",
        title_base_url="https://api.siliconflow.cn/v1", title_api_key="fake-title-key",
        thinking_enabled=True, reasoning_effort="high",
        base_url="https://api.deepseek.com/anthropic", api_key="fake-key", auth_token=None,
        api_timeout=2, max_output_tokens=32768, command_timeout=5, max_rounds=5, max_seconds=10, token_threshold=100000,
        visual=False, trace_output_limit=300, permission_mode="approval",
        allow_critical=False, fake_client=True, poll_interval=1, idle_timeout=1,
    )
    values.update(overrides)
    return Settings(**values)
