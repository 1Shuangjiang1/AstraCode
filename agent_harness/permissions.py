from __future__ import annotations

import hashlib
import re
import shlex
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Callable


class Risk(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Decision:
    allowed: bool
    risk: Risk
    reasons: list[str] = field(default_factory=list)
    needs_approval: bool = False
    cached: bool = False

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) or "low-risk operation"


class PermissionEngine:
    MODES = {"safe", "approval", "full_access"}
    CRITICAL_PATTERNS = [
        (r"\brm\s+-[^\n]*r[^\n]*f\s+[/~](?:\s|$)", "recursive deletion of a broad root"),
        (r"\b(?:mkfs|diskpart|format)\b", "disk formatting operation"),
        (r"\b(?:shutdown|reboot|poweroff)\b", "machine power operation"),
        (r"\bdd\s+if=", "raw block-device write"),
        (r"remove-item\b[^\n]*(?:-recurse|-r)\b[^\n]*(?:\\|/)(?:\s|$)", "broad recursive deletion"),
    ]
    HIGH_PATTERNS = [
        (r"\b(?:rm|del|erase|rmdir|remove-item)\b", "deletes files"),
        (r"\bgit\s+(?:reset\s+--hard|clean\s+-|push\s+.*--force)", "destructive git operation"),
        (r"\b(?:sudo|runas)\b", "requests elevated privileges"),
        (r"(?:^|\s)(?:>|2>|&>)\s*(?:/etc/|[a-z]:\\windows\\)", "writes to a system path"),
        (r"\b(?:chmod\s+777|takeown|icacls)\b", "changes broad permissions"),
    ]
    MEDIUM_PATTERNS = [
        (r"\b(?:pip|npm|pnpm|yarn|winget|choco)\s+(?:install|uninstall|remove)\b", "changes installed packages"),
        (r"\b(?:curl|wget|invoke-webrequest)\b", "accesses the network"),
        (r"\b(?:git\s+commit|git\s+push)\b", "changes repository or remote state"),
        (r"\b(?:kill|taskkill|stop-process)\b", "stops a process"),
    ]

    def __init__(self, workdir: Path, mode: str = "approval", allow_critical: bool = False,
                 prompt: Callable[[str, dict, Decision, str], str] | None = None,
                 dynamic_workspace: bool = False):
        self.workdir = workdir.resolve()
        self.workspace_root = self.workdir
        self.dynamic_workspace = dynamic_workspace
        self.mode = mode if mode in self.MODES else "approval"
        self.allow_critical = allow_critical
        self.prompt = prompt or self._console_prompt
        self._session_approvals: set[str] = set()
        self._lock = threading.RLock()
        self._prompt_lock = threading.Lock()

    def set_mode(self, mode: str):
        aliases = {"full": "full_access", "ask": "approval"}
        mode = aliases.get(mode.lower(), mode.lower())
        if mode not in self.MODES:
            raise ValueError(f"Unknown mode '{mode}'. Choose safe, approval, or full_access.")
        with self._lock:
            self.mode = mode

    def set_workdir(self, workdir: Path):
        with self._lock:
            self.workdir = workdir.resolve()
            if self.dynamic_workspace:
                self.workspace_root = self.workdir

    @contextmanager
    def input_guard(self):
        """Coordinates REPL input with approval prompts from worker threads."""
        with self._prompt_lock:
            yield

    def _resolved_path(self, raw: str) -> Path:
        return (self.workdir / raw).resolve()

    def assess(self, tool_name: str, args: dict) -> Decision:
        reasons, risk = [], Risk.LOW
        if tool_name == "set_working_directory":
            raw = str(args.get("path", ""))
            try:
                target = self._resolved_path(raw)
                outside = not target.is_relative_to(self.workspace_root)
            except (OSError, ValueError):
                outside = True
            if outside:
                risk = Risk.HIGH
                reasons.append("changes the active workspace directory")
            else:
                risk = Risk.LOW
                reasons.append("selects a directory inside the active workspace")
        if tool_name in {"write_file", "edit_file", "read_file", "list_directory", "path_exists", "delete_file"}:
            raw = str(args.get("path", ""))
            try:
                outside = not self._resolved_path(raw).is_relative_to(self.workspace_root)
            except (OSError, ValueError):
                outside = True
            if outside:
                risk = Risk.HIGH
                reasons.append("path is outside the workspace")
            elif tool_name in {"write_file", "edit_file"}:
                risk = Risk.MEDIUM
                reasons.append("modifies a workspace file")
            elif tool_name == "delete_file":
                risk = Risk.MEDIUM
                reasons.append("deletes one exact workspace file")
        if tool_name in {"bash", "background_run"}:
            command = str(args.get("command", "")).strip()
            normalized = re.sub(r"\s+", " ", command).lower()
            for pattern, reason in self.CRITICAL_PATTERNS:
                if re.search(pattern, normalized, re.IGNORECASE):
                    risk = max(risk, Risk.CRITICAL)
                    reasons.append(reason)
            for pattern, reason in self.HIGH_PATTERNS:
                if re.search(pattern, normalized, re.IGNORECASE):
                    risk = max(risk, Risk.HIGH)
                    reasons.append(reason)
            for pattern, reason in self.MEDIUM_PATTERNS:
                if re.search(pattern, normalized, re.IGNORECASE):
                    risk = max(risk, Risk.MEDIUM)
                    reasons.append(reason)
            if any(op in command for op in (";", "&&", "||", "|")):
                risk = max(risk, Risk.MEDIUM)
                reasons.append("chains multiple shell operations")
        return Decision(True, risk, list(dict.fromkeys(reasons)))

    def _fingerprint(self, tool_name: str, args: dict, decision: Decision) -> str:
        stable = f"{tool_name}|{decision.risk.name}|{decision.reason}|{sorted(args.keys())}"
        return hashlib.sha256(stable.encode()).hexdigest()

    def authorize(self, tool_name: str, args: dict, actor: str = "lead") -> Decision:
        decision = self.assess(tool_name, args)
        if decision.risk == Risk.CRITICAL and not self.allow_critical:
            decision.allowed = False
            decision.reasons.append("critical operations require S_FULL_ALLOW_CRITICAL=1")
            return decision
        if self.mode == "full_access":
            return decision
        if self.mode == "safe":
            decision.allowed = decision.risk < Risk.MEDIUM
            return decision
        if decision.risk < Risk.HIGH:
            return decision
        fingerprint = self._fingerprint(tool_name, args, decision)
        with self._lock:
            if fingerprint in self._session_approvals:
                decision.cached = True
                return decision
        decision.needs_approval = True
        # Only one agent may own the terminal approval prompt at a time.
        with self._prompt_lock:
            choice = self.prompt(tool_name, args, decision, actor).strip().lower()
        decision.allowed = choice in {"y", "yes", "a", "always"}
        if choice in {"a", "always"}:
            with self._lock:
                self._session_approvals.add(fingerprint)
        return decision

    @staticmethod
    def _console_prompt(tool_name: str, args: dict, decision: Decision, actor: str) -> str:
        print(f"\nPermission approval [{decision.risk.name}] actor={actor}")
        print(f"  Tool: {tool_name} {args}")
        print(f"  Why: {decision.reason}")
        try:
            return input("  Allow? [y] once / [a] similar this session / [N] deny: ")
        except (EOFError, KeyboardInterrupt):
            return "n"
