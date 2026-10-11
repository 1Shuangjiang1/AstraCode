from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def user_config_path() -> Path:
    """Persistent per-user provider config used by installed desktop builds."""
    local = os.getenv("LOCALAPPDATA", "").strip()
    root = Path(local) / "AstraCode" if local else Path.home() / ".astracode"
    return root.resolve() / "config.env"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no"}


@dataclass(frozen=True)
class Settings:
    workdir: Path
    model: str
    title_model: str
    title_base_url: str
    title_api_key: str | None
    thinking_enabled: bool
    reasoning_effort: str
    base_url: str | None
    api_key: str | None
    auth_token: str | None
    api_timeout: float
    max_output_tokens: int
    command_timeout: int
    max_rounds: int
    max_seconds: float
    token_threshold: int
    visual: bool
    trace_output_limit: int
    permission_mode: str
    allow_critical: bool
    fake_client: bool
    poll_interval: int
    idle_timeout: int
    state_root: Path | None = None

    @classmethod
    def from_env(cls, workdir: Path | None = None) -> "Settings":
        workdir = (workdir or Path.cwd()).resolve()
        package_root = Path(__file__).resolve().parent.parent
        # Explicit process variables (including run.ps1 flags) have highest priority.
        # A caller-provided workdir config wins over the package fallback.
        for env_path in (user_config_path(), workdir / ".env", package_root / ".env"):
            if env_path.exists():
                load_dotenv(env_path, override=False)
        load_dotenv(override=False)
        mode = os.getenv("S_FULL_PERMISSION_MODE", "approval").strip().lower()
        aliases = {"ask": "approval", "approve": "approval", "full": "full_access"}
        mode = aliases.get(mode, mode)
        if mode not in {"safe", "approval", "full_access"}:
            mode = "approval"
        effort = os.getenv("S_FULL_REASONING_EFFORT", "high").strip().lower()
        effort = {"xhigh": "max", "medium": "high", "low": "high"}.get(effort, effort)
        if effort not in {"high", "max"}:
            effort = "high"
        return cls(
            workdir=workdir,
            model=os.getenv("S_FULL_MODEL") or os.getenv("MODEL_ID") or "deepseek-v4-flash",
            title_model=os.getenv("S_FULL_TITLE_MODEL") or "deepseek-ai/DeepSeek-V4-Flash",
            title_base_url=os.getenv("S_FULL_TITLE_BASE_URL") or "https://api.siliconflow.cn/v1",
            title_api_key=os.getenv("S_FULL_TITLE_API_KEY") or None,
            thinking_enabled=_as_bool(os.getenv("S_FULL_THINKING"), True),
            reasoning_effort=effort,
            base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
            api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or None,
            auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN") or None,
            api_timeout=float(os.getenv("S_FULL_API_TIMEOUT", "120")),
            max_output_tokens=max(1000, int(os.getenv("S_FULL_MAX_OUTPUT_TOKENS", "32768"))),
            command_timeout=int(os.getenv("S_FULL_COMMAND_TIMEOUT", "30")),
            max_rounds=int(os.getenv("S_FULL_MAX_ROUNDS", "8")),
            max_seconds=float(os.getenv("S_FULL_MAX_SECONDS", "300")),
            token_threshold=int(os.getenv("S_FULL_TOKEN_THRESHOLD", "100000")),
            visual=_as_bool(os.getenv("S_FULL_VISUAL"), True),
            trace_output_limit=int(os.getenv("S_FULL_TRACE_OUTPUT_LIMIT", "1200")),
            permission_mode=mode,
            allow_critical=_as_bool(os.getenv("S_FULL_ALLOW_CRITICAL"), False),
            fake_client=_as_bool(os.getenv("S_FULL_FAKE_CLIENT"), False),
            poll_interval=int(os.getenv("S_FULL_POLL_INTERVAL", "5")),
            idle_timeout=int(os.getenv("S_FULL_IDLE_TIMEOUT", "60")),
            state_root=Path(os.environ["S_FULL_STATE_DIR"]).expanduser().resolve() if os.getenv("S_FULL_STATE_DIR") else None,
        )

    @property
    def internal_root(self) -> Path:
        return self.state_root or self.workdir

    @property
    def team_dir(self) -> Path:
        return self.internal_root / ".team"

    @property
    def task_dir(self) -> Path:
        return self.internal_root / ".tasks"

    @property
    def skill_dir(self) -> Path:
        return self.workdir / "skills"

    @property
    def skill_dirs(self) -> tuple[Path, ...]:
        """Built-in skills first; project-local skills may override by name."""
        built_in = Path(__file__).resolve().parent.parent / "skills"
        project = self.skill_dir
        return (built_in,) if project == built_in else (built_in, project)

    @property
    def transcript_dir(self) -> Path:
        return self.internal_root / ".transcripts"

    @property
    def memory_dir(self) -> Path:
        return self.internal_root / ".memory"


class _MessagesWithDefaults:
    """Inject provider-wide request options into every model call."""

    def __init__(self, messages, defaults: dict):
        self._messages = messages
        self._defaults = defaults

    def create(self, **kwargs):
        for key, value in self._defaults.items():
            kwargs.setdefault(key, value)
        return self._messages.create(**kwargs)


class _ConfiguredClient:
    def __init__(self, client, defaults: dict):
        self._client = client
        self.messages = _MessagesWithDefaults(client.messages, defaults)

    def __getattr__(self, name):
        return getattr(self._client, name)


def create_client(settings: Settings):
    if settings.fake_client:
        from .fake_client import FakeAnthropic
        return FakeAnthropic()
    from anthropic import Anthropic
    kwargs = {"timeout": settings.api_timeout}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.auth_token:
        kwargs["auth_token"] = settings.auth_token
    elif settings.api_key:
        kwargs["api_key"] = settings.api_key
    client = Anthropic(**kwargs)
    defaults = {
        "thinking": {"type": "enabled" if settings.thinking_enabled else "disabled"},
    }
    if settings.thinking_enabled:
        defaults["output_config"] = {"effort": settings.reasoning_effort}
    return _ConfiguredClient(client, defaults)
