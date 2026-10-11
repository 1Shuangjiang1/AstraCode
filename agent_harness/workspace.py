from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from queue import Queue

from .concurrency import WorkspaceCoordinator
from .permissions import PermissionEngine
from .ui import Console, tool_label
from .tool_validation import validate_tool_input


class WorkspaceTools:
    def __init__(self, workdir: Path, coordinator: WorkspaceCoordinator,
                 cancel_event: threading.Event | None = None, default_timeout: int = 30,
                 unrestricted: bool = False, require_directory_selection: bool = False):
        self.workdir = workdir.resolve()
        self.workspace_root = self.workdir
        self.unrestricted = unrestricted
        self.directory_selected = not require_directory_selection
        self.coordinator = coordinator
        self.cancel_event = cancel_event or threading.Event()
        self.default_timeout = default_timeout
        self._process_lock = threading.RLock()
        self._active_processes: set[subprocess.Popen] = set()

    def safe_path(self, raw: str) -> Path:
        if not self.directory_selected:
            raise ValueError("Chat mode has no active directory; call set_working_directory first")
        candidate = Path(raw).expanduser()
        path = (candidate if candidate.is_absolute() else self.workdir / candidate).resolve()
        if not self.unrestricted and not path.is_relative_to(self.workspace_root):
            raise ValueError(f"Path escapes workspace: {raw}")
        return path

    def set_working_directory(self, path: str, actor: str = "lead") -> str:
        try:
            candidate = Path(path).expanduser()
            target = (candidate if candidate.is_absolute() else self.workdir / candidate).resolve()
            with self.coordinator.access(actor, f"set directory: {target}"):
                if not target.is_dir():
                    return f"Error: Directory does not exist: {path}"
                if not self.unrestricted and not target.is_relative_to(self.workspace_root):
                    return f"Error: Directory is outside the project workspace: {path}"
                self.workdir = target
                self.directory_selected = True
            return f"Working directory: {target}"
        except Exception as exc:
            return f"Error: {exc}"

    def _shell_command(self, command: str) -> list[str]:
        if os.name == "nt":
            executable = shutil.which("pwsh") or shutil.which("powershell")
            if not executable:
                raise RuntimeError("PowerShell is not installed or not available on PATH")
            # PowerShell requires the call operator for a quoted executable path.
            if re.match(r'^\s*"[^"]+\.exe"(?:\s|$)', command, re.IGNORECASE):
                command = "& " + command
            wrapped = (
                "$ErrorActionPreference='Stop'; "
                "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
                "$OutputEncoding=[Console]::OutputEncoding; $global:LASTEXITCODE=0; "
                f"& {{ {command} }}; if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}"
            )
            return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wrapped]
        executable = shutil.which("bash") or shutil.which("sh")
        if not executable:
            raise RuntimeError("No supported shell is installed")
        return [executable, "-lc", command]

    def bash(self, command: str, timeout: int | None = None, actor: str = "lead") -> str:
        process: subprocess.Popen | None = None
        timeout = self.default_timeout if timeout is None else max(1, int(timeout))
        try:
            if not self.directory_selected:
                return "Error: Chat mode has no active directory; call set_working_directory first"
            with self.coordinator.access(actor, f"bash: {command[:80]}"):
                options = {
                    "shell": False,
                    "cwd": self.workdir,
                    # Never inherit the long-lived desktop sidecar JSONL input pipe.
                    # Tools are explicitly non-interactive; inherited stdin can keep
                    # PowerShell/native children alive even after their work is done.
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                    "env": {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                }
                if os.name == "nt":
                    options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    options["start_new_session"] = True
                process = subprocess.Popen(self._shell_command(command), **options)
                with self._process_lock:
                    self._active_processes.add(process)
                deadline = time.monotonic() + timeout
                while True:
                    if self.cancel_event.is_set():
                        self._terminate_process_tree(process)
                        return "Error: Cancelled by user"
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._terminate_process_tree(process)
                        return f"Error: Timeout ({timeout}s)"
                    try:
                        stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            output = ((stdout or "") + (stderr or "")).strip()
            if process.returncode:
                detail = output[:50000] if output else "(no output)"
                return f"Error: Command exited with code {process.returncode}\n{detail}"
            return output[:50000] if output else "(no output)"
        except Exception as exc:
            return f"Error: {exc}"
        finally:
            if process is not None:
                with self._process_lock:
                    self._active_processes.discard(process)

    def cancel_active(self) -> None:
        # Let the owning bash loop perform the single termination/drain path.
        # Calling taskkill here as well races communicate() on Windows and can
        # leave the child's cwd/stdout handles alive briefly after cancellation.
        self.cancel_event.set()

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=3, check=False,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        # communicate() closes our pipe handles after the process tree exits.
        # This matters on Windows where an open child handle can prevent the
        # selected working directory from being renamed or removed.
        try:
            process.communicate(timeout=0.5)
        except (OSError, subprocess.SubprocessError):
            pass

    def read(self, path: str, limit: int | None = None, actor: str = "lead") -> str:
        try:
            with self.coordinator.access(actor, f"read: {path}"):
                lines = self.safe_path(path).read_text(encoding="utf-8").splitlines()
            if limit and limit < len(lines):
                lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
            return "\n".join(lines)[:50000]
        except Exception as exc:
            return f"Error: {exc}"

    def list_directory(self, path: str = ".", actor: str = "lead") -> str:
        try:
            with self.coordinator.access(actor, f"list: {path}"):
                target = self.safe_path(path)
                if not target.is_dir():
                    return f"Error: Not a directory: {path}"
                entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
                lines = [f"{'directory' if item.is_dir() else 'file'}\t{item.name}" for item in entries[:500]]
            if len(entries) > 500:
                lines.append(f"... ({len(entries) - 500} more entries)")
            return "\n".join(lines) or "(empty directory)"
        except Exception as exc:
            return f"Error: {exc}"

    def path_exists(self, path: str, actor: str = "lead") -> str:
        try:
            with self.coordinator.access(actor, f"exists: {path}"):
                target = self.safe_path(path)
                if not target.exists():
                    return f"absent: {path}"
                kind = "directory" if target.is_dir() else "file"
                return f"exists ({kind}): {path}"
        except Exception as exc:
            return f"Error: {exc}"

    def write(self, path: str, content: str, actor: str = "lead") -> str:
        try:
            with self.coordinator.access(actor, f"write: {path}"):
                target = self.safe_path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as exc:
            return f"Error: {exc}"

    def edit(self, path: str, old_text: str, new_text: str, actor: str = "lead") -> str:
        try:
            with self.coordinator.access(actor, f"edit: {path}"):
                target = self.safe_path(path)
                content = target.read_text(encoding="utf-8")
                count = content.count(old_text)
                if count == 0:
                    return f"Error: Text not found in {path}"
                if count > 1:
                    return f"Error: Text appears {count} times in {path}; provide a unique match"
                target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path}"
        except Exception as exc:
            return f"Error: {exc}"

    def delete_file(self, path: str, actor: str = "lead") -> str:
        try:
            with self.coordinator.access(actor, f"delete: {path}"):
                target = self.safe_path(path)
                if not target.exists():
                    return f"Already absent: {path}"
                if not target.is_file():
                    return f"Error: Refusing to delete a directory with delete_file: {path}"
                target.unlink()
            return f"Deleted file: {path}"
        except Exception as exc:
            return f"Error: {exc}"


class ToolExecutor:
    """One permission and execution gateway shared by every kind of agent."""

    def __init__(self, permission: PermissionEngine, console: Console):
        self.permission = permission
        self.console = console

    def execute(self, tool_name: str, args: dict, handler, actor: str = "lead") -> str:
        validation_error = validate_tool_input(tool_name, args)
        if validation_error:
            output = f"Error: Invalid arguments for {tool_name}: {validation_error}. Retry with a complete tool call."
            self.console.log("工具参数", f"{actor}: {tool_label(tool_name)} 参数无效", output, "red")
            return output
        decision = self.permission.authorize(tool_name, args, actor)
        self.console.log(
            "权限判断", f"{actor}: {decision.risk.name} {'允许' if decision.allowed else '拒绝'}",
            decision.reason, "green" if decision.allowed else "red",
        )
        if not decision.allowed:
            return f"Permission denied [{decision.risk.name}]: {decision.reason}"
        started = time.monotonic()
        try:
            output = handler(**args)
        except Exception as exc:
            output = f"Error: {exc}"
        elapsed = time.monotonic() - started
        if tool_name == "set_working_directory" and not str(output).startswith("Error:"):
            try:
                self.permission.set_workdir(Path(str(output).split(": ", 1)[1]))
            except (IndexError, OSError, ValueError):
                pass
        self.console.log("工具结果", f"{actor}: {tool_label(tool_name)} ({elapsed:.2f}s)", output,
                         "red" if str(output).lower().startswith("error") else "green")
        return str(output)


class BackgroundManager:
    def __init__(self, tools: WorkspaceTools, console: Console):
        self.tools = tools
        self.console = console
        self.tasks: dict[str, dict] = {}
        self.notifications = Queue()
        self._lock = threading.RLock()

    def run(self, command: str, timeout: int = 120, actor: str = "lead") -> str:
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self.tasks[task_id] = {"status": "running", "command": command, "result": None}
        threading.Thread(target=self._exec, args=(task_id, command, timeout, actor), daemon=True).start()
        return f"Background task {task_id} started: {command[:80]}"

    def _exec(self, task_id: str, command: str, timeout: int, actor: str):
        result = self.tools.bash(command, timeout, f"{actor}/background:{task_id}")
        status = "error" if result.startswith("Error:") else "completed"
        with self._lock:
            self.tasks[task_id].update({"status": status, "result": result})
        self.notifications.put({"task_id": task_id, "status": status, "result": result[:500]})
        self.console.log("后台任务", f"{task_id} {status}", result, "green" if status == "completed" else "red")

    def check(self, task_id: str | None = None) -> str:
        with self._lock:
            if task_id:
                task = self.tasks.get(task_id)
                return f"[{task['status']}] {task.get('result') or '(running)'}" if task else f"Unknown: {task_id}"
            return "\n".join(f"{key}: [{value['status']}] {value['command'][:60]}"
                              for key, value in self.tasks.items()) or "No bg tasks."

    def drain(self) -> list:
        items = []
        while not self.notifications.empty():
            items.append(self.notifications.get_nowait())
        return items
