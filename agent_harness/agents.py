from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .schemas import FILE_TOOLS, TEAMMATE_TOOLS
from .message_protocol import repair_tool_protocol
from .state import MessageBus, TaskManager, atomic_write
from .ui import Console, content_blocks_summary, text_content, tool_label
from .workspace import ToolExecutor, WorkspaceTools


class SubagentRunner:
    def __init__(self, client, model: str, tools: WorkspaceTools,
                 executor: ToolExecutor, console: Console, max_output_tokens: int = 32768,
                 event_callback: Callable[..., None] | None = None):
        self.client = client
        self.model = model
        self.tools = tools
        self.executor = executor
        self.console = console
        self.max_output_tokens = max_output_tokens
        self.event_callback = event_callback

    def _emit(self, event_type: str, **payload):
        if self.event_callback:
            self.event_callback(event_type, **payload)

    def _handler(self, actor: str, name: str):
        handlers = {
            "set_working_directory": lambda path: self.tools.set_working_directory(path, actor),
            "bash": lambda command: self.tools.bash(command, actor=actor),
            "read_file": lambda path, limit=None: self.tools.read(path, limit, actor),
            "list_directory": lambda path=".": self.tools.list_directory(path, actor),
            "path_exists": lambda path: self.tools.path_exists(path, actor),
            "write_file": lambda path, content: self.tools.write(path, content, actor),
            "edit_file": lambda path, old_text, new_text: self.tools.edit(path, old_text, new_text, actor),
            "delete_file": lambda path: self.tools.delete_file(path, actor),
        }
        return handlers.get(name)

    def run(self, prompt: str, agent_type: str = "Explore") -> str:
        actor = f"subagent:{uuid.uuid4().hex[:6]}"
        allowed_names = {"bash", "read_file", "list_directory", "path_exists"} if agent_type == "Explore" else {tool["name"] for tool in FILE_TOOLS}
        schemas = [tool for tool in FILE_TOOLS if tool["name"] in allowed_names]
        messages = [{"role": "user", "content": prompt}]
        response = None
        self._emit("agent_started", agent_id=actor, agent_kind="subagent", name=agent_type,
                   role=agent_type, prompt=prompt)
        try:
            for round_no in range(1, 31):
                repair_tool_protocol(messages)
                self._emit("agent_status", agent_id=actor, agent_kind="subagent", name=agent_type,
                           status="thinking", round=round_no)
                self.console.log("子Agent", f"{actor} 第 {round_no} 轮", prompt if round_no == 1 else None, "magenta")
                response = self.client.messages.create(
                    model=self.model, messages=messages, tools=schemas,
                    max_tokens=self.max_output_tokens,
                )
                messages.append({"role": "assistant", "content": response.content})
                text = text_content(response.content).strip()
                if text:
                    self._emit("agent_message", agent_id=actor, agent_kind="subagent", name=agent_type,
                               content=text[:4000], round=round_no)
                tool_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
                if not tool_blocks:
                    break
                results = []
                for block in tool_blocks:
                    self._emit("agent_tool_started", agent_id=actor, agent_kind="subagent", name=agent_type,
                               tool=block.name, detail=str(block.input.get("path") or block.input.get("command") or "")[:600])
                    handler = self._handler(actor, block.name)
                    output = self.executor.execute(block.name, block.input, handler, actor) if handler else "Unknown tool"
                    ok = not str(output).lower().startswith(("error", "permission denied"))
                    self._emit("agent_tool_completed", agent_id=actor, agent_kind="subagent", name=agent_type,
                               tool=block.name, ok=ok, result=str(output)[:1200])
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output[:50000]})
                messages.append({"role": "user", "content": results})
        except Exception as exc:
            self._emit("agent_failed", agent_id=actor, agent_kind="subagent", name=agent_type,
                       status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        if not response:
            self._emit("agent_failed", agent_id=actor, agent_kind="subagent", name=agent_type,
                       status="failed", error="No model response")
            return "(subagent failed)"
        summary = text_content(response.content) or "(no summary)"
        self._emit("agent_completed", agent_id=actor, agent_kind="subagent", name=agent_type,
                   status="completed", summary=summary[:4000])
        return summary


class TeammateManager:
    def __init__(self, directory: Path, client, model: str, bus: MessageBus,
                 task_manager: TaskManager, tools: WorkspaceTools, executor: ToolExecutor,
                 console: Console, poll_interval: int = 5, idle_timeout: int = 60,
                 max_output_tokens: int = 32768,
                 event_callback: Callable[..., None] | None = None):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config_path = directory / "config.json"
        self.client, self.model, self.bus = client, model, bus
        self.task_manager, self.tools, self.executor = task_manager, tools, executor
        self.console = console
        self.poll_interval, self.idle_timeout = poll_interval, idle_timeout
        self.max_output_tokens = max_output_tokens
        self.event_callback = event_callback
        self._lock = threading.RLock()
        self.config = self._load()
        self.threads: dict[str, threading.Thread] = {}

    def _emit(self, event_type: str, **payload):
        if self.event_callback:
            self.event_callback(event_type, **payload)

    def _load(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {"team_name": "default", "members": []}

    def _save(self):
        atomic_write(self.config_path, json.dumps(self.config, indent=2, ensure_ascii=False))

    def _find(self, name: str) -> dict | None:
        return next((member for member in self.config["members"] if member["name"] == name), None)

    def _set_status(self, name: str, status: str):
        with self._lock:
            member = self._find(name)
            if member:
                member["status"] = status
                self._save()
        self.console.log("队友状态", f"{name} -> {status}", color="magenta")
        self._emit("agent_status", agent_id=f"teammate:{name}", agent_kind="teammate",
                   name=name, status=status)

    def spawn(self, name: str, role: str, prompt: str) -> str:
        with self._lock:
            member = self._find(name)
            if member and member["status"] not in {"idle", "shutdown"}:
                return f"Error: '{name}' is currently {member['status']}"
            if member:
                member.update({"role": role, "status": "working"})
            else:
                self.config["members"].append({"name": name, "role": role, "status": "working"})
            self._save()
            self._emit("agent_started", agent_id=f"teammate:{name}", agent_kind="teammate",
                       name=name, role=role, prompt=prompt, status="working")
            thread = threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True)
            self.threads[name] = thread
            thread.start()
        return f"Spawned '{name}' (role: {role})"

    def _handler(self, name: str, tool_name: str):
        actor = f"teammate:{name}"
        handlers = {
            "set_working_directory": lambda path: self.tools.set_working_directory(path, actor),
            "bash": lambda command: self.tools.bash(command, actor=actor),
            "read_file": lambda path, limit=None: self.tools.read(path, limit, actor),
            "list_directory": lambda path=".": self.tools.list_directory(path, actor),
            "path_exists": lambda path: self.tools.path_exists(path, actor),
            "write_file": lambda path, content: self.tools.write(path, content, actor),
            "edit_file": lambda path, old_text, new_text: self.tools.edit(path, old_text, new_text, actor),
            "delete_file": lambda path: self.tools.delete_file(path, actor),
            "send_message": lambda to, content: self.bus.send(name, to, content),
            "claim_task": lambda task_id: self.task_manager.claim(task_id, name),
            "idle": lambda: "Entering idle phase.",
        }
        return handlers.get(tool_name)

    def _loop(self, name: str, role: str, prompt: str):
        actor = f"teammate:{name}"
        system = (f"You are '{name}', role: {role}, team: {self.config['team_name']}. "
                  "Use idle when done. You may claim available tasks.")
        messages = [{"role": "user", "content": prompt}]
        try:
            while True:
                idle_requested = False
                for round_no in range(1, 51):
                    repair_tool_protocol(messages)
                    for item in self.bus.read_inbox(name):
                        if item.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(item, ensure_ascii=False)})
                    self._emit("agent_status", agent_id=actor, agent_kind="teammate", name=name,
                               status="thinking", round=round_no)
                    response = self.client.messages.create(model=self.model, system=system,
                        messages=messages, tools=TEAMMATE_TOOLS, max_tokens=self.max_output_tokens)
                    messages.append({"role": "assistant", "content": response.content})
                    text = text_content(response.content).strip()
                    if text:
                        self._emit("agent_message", agent_id=actor, agent_kind="teammate", name=name,
                                   content=text[:4000], round=round_no)
                    self.console.log("队友Agent", f"{name}: {response.stop_reason}",
                                     content_blocks_summary(response.content), "magenta")
                    tool_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
                    if not tool_blocks:
                        break
                    results = []
                    for block in tool_blocks:
                        idle_requested |= block.name == "idle"
                        self._emit("agent_tool_started", agent_id=actor, agent_kind="teammate", name=name,
                                   tool=block.name, detail=str(block.input.get("path") or block.input.get("command") or "")[:600])
                        handler = self._handler(name, block.name)
                        output = self.executor.execute(block.name, block.input, handler, actor) if handler else "Unknown tool"
                        self._emit("agent_tool_completed", agent_id=actor, agent_kind="teammate", name=name,
                                   tool=block.name,
                                   ok=not str(output).lower().startswith(("error", "permission denied")),
                                   result=str(output)[:1200])
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                    messages.append({"role": "user", "content": results})
                    if idle_requested:
                        break
                self._set_status(name, "idle")
                resumed = False
                for _ in range(max(1, self.idle_timeout // max(1, self.poll_interval))):
                    time.sleep(self.poll_interval)
                    inbox = self.bus.read_inbox(name)
                    if inbox:
                        if any(item.get("type") == "shutdown_request" for item in inbox):
                            self._set_status(name, "shutdown")
                            return
                        messages.extend({"role": "user", "content": json.dumps(item, ensure_ascii=False)} for item in inbox)
                        resumed = True
                        break
                    available = [task for task in self.task_manager.list_data()
                                 if task.get("status") == "pending" and not task.get("owner") and not task.get("blockedBy")]
                    if available:
                        task = available[0]
                        self.task_manager.claim(task["id"], name)
                        messages.append({"role": "user", "content":
                            f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>"})
                        resumed = True
                        break
                if not resumed:
                    self._set_status(name, "shutdown")
                    self._emit("agent_completed", agent_id=actor, agent_kind="teammate", name=name,
                               status="completed", summary="Teammate entered shutdown after its idle window.")
                    return
                self._set_status(name, "working")
        except Exception as exc:
            self.console.log("队友Agent", f"{name} 失败", str(exc), "red")
            self._emit("agent_failed", agent_id=actor, agent_kind="teammate", name=name,
                       status="failed", error=f"{type(exc).__name__}: {exc}")
            self._set_status(name, "shutdown")

    def list_all(self) -> str:
        with self._lock:
            if not self.config["members"]:
                return "No teammates."
            return "\n".join([f"Team: {self.config['team_name']}"] +
                [f"  {member['name']} ({member['role']}): {member['status']}" for member in self.config["members"]])

    def member_names(self) -> list[str]:
        with self._lock:
            return [member["name"] for member in self.config["members"]]
