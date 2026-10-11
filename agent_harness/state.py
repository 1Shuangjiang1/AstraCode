from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path


def atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


class TodoManager:
    def __init__(self):
        self.items: list[dict] = []
        self._lock = threading.RLock()

    def update(self, items: list) -> str:
        validated, in_progress = [], 0
        for index, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active = str(item.get("activeForm", "")).strip()
            if not content or not active:
                raise ValueError(f"Item {index}: content and activeForm required")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"Item {index}: invalid status '{status}'")
            in_progress += status == "in_progress"
            validated.append({"content": content, "status": status, "activeForm": active})
        if len(validated) > 20 or in_progress > 1:
            raise ValueError("Max 20 todos and only one in_progress item")
        with self._lock:
            self.items = validated
            return self.render()

    def render(self) -> str:
        with self._lock:
            if not self.items:
                return "No todos."
            marks = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}
            lines = [f"{marks[item['status']]} {item['content']}" +
                     (f" <- {item['activeForm']}" if item["status"] == "in_progress" else "")
                     for item in self.items]
            done = sum(item["status"] == "completed" for item in self.items)
            return "\n".join(lines + [f"\n({done}/{len(self.items)} completed)"])

    def has_open_items(self) -> bool:
        with self._lock:
            return any(item["status"] != "completed" for item in self.items)

    def has_items(self) -> bool:
        with self._lock:
            return bool(self.items)

    def progress(self) -> tuple[int, int]:
        with self._lock:
            return sum(item["status"] == "completed" for item in self.items), len(self.items)


class SkillLoader:
    def __init__(self, skills_dir: Path | tuple[Path, ...] | list[Path]):
        self.skills = {}
        directories = (skills_dir,) if isinstance(skills_dir, Path) else tuple(skills_dir)
        for directory in directories:
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("SKILL.md")):
                text = path.read_text(encoding="utf-8")
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            key, value = line.split(":", 1)
                            meta[key.strip()] = value.strip()
                    body = match.group(2).strip()
                self.skills[meta.get("name", path.parent.name)] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        return "\n".join(f"  - {name}: {skill['meta'].get('description', '-')}"
                          for name, skill in self.skills.items()) or "(no skills)"

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"name": name, "description": str(skill["meta"].get("description", "-"))}
            for name, skill in sorted(self.skills.items())
        ]

    def load(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills)}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"


class TaskManager:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, task_id: int) -> Path:
        return self.directory / f"task_{task_id}.json"

    def _load(self, task_id: int) -> dict:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, task: dict):
        atomic_write(self._path(task["id"]), json.dumps(task, indent=2, ensure_ascii=False))

    def create(self, subject: str, description: str = "") -> str:
        with self._lock:
            ids = [int(path.stem.split("_")[1]) for path in self.directory.glob("task_*.json")]
            task = {"id": max(ids, default=0) + 1, "subject": subject, "description": description,
                    "status": "pending", "owner": None, "blockedBy": []}
            self._save(task)
            return json.dumps(task, indent=2, ensure_ascii=False)

    def get(self, task_id: int) -> str:
        with self._lock:
            return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)

    def update(self, task_id: int, status: str | None = None,
               add_blocked_by: list | None = None, remove_blocked_by: list | None = None) -> str:
        with self._lock:
            task = self._load(task_id)
            if status == "deleted":
                self._path(task_id).unlink(missing_ok=True)
                return f"Task {task_id} deleted"
            if status:
                task["status"] = status
            if status == "completed":
                for path in self.directory.glob("task_*.json"):
                    other = json.loads(path.read_text(encoding="utf-8"))
                    if task_id in other.get("blockedBy", []):
                        other["blockedBy"].remove(task_id)
                        self._save(other)
            if add_blocked_by:
                task["blockedBy"] = sorted(set(task["blockedBy"] + add_blocked_by))
            if remove_blocked_by:
                task["blockedBy"] = [item for item in task["blockedBy"] if item not in remove_blocked_by]
            self._save(task)
            return json.dumps(task, indent=2, ensure_ascii=False)

    def list_data(self) -> list[dict]:
        with self._lock:
            return [json.loads(path.read_text(encoding="utf-8"))
                    for path in sorted(self.directory.glob("task_*.json"))]

    def list_all(self) -> str:
        tasks = self.list_data()
        if not tasks:
            return "No tasks."
        marks = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
        return "\n".join(
            f"{marks.get(task['status'], '[?]')} #{task['id']}: {task['subject']}" +
            (f" @{task['owner']}" if task.get("owner") else "") +
            (f" (blocked by: {task['blockedBy']})" if task.get("blockedBy") else "")
            for task in tasks
        )

    def claim(self, task_id: int, owner: str) -> str:
        with self._lock:
            task = self._load(task_id)
            if task.get("owner") and task["owner"] != owner:
                return f"Error: Task {task_id} already owned by {task['owner']}"
            task.update({"owner": owner, "status": "in_progress"})
            self._save(task)
            return f"Claimed task #{task_id} for {owner}"


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.inbox_dir = inbox_dir
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def send(self, sender: str, to: str, content: str, msg_type: str = "message", extra: dict | None = None) -> str:
        message = {"type": msg_type, "from": sender, "content": content, "timestamp": time.time()}
        if extra:
            message.update(extra)
        with self._lock:
            path = self.inbox_dir / f"{to}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        path = self.inbox_dir / f"{name}.jsonl"
        with self._lock:
            if not path.exists():
                return []
            messages = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            atomic_write(path, "")
            return messages

    def broadcast(self, sender: str, content: str, names: list[str]) -> str:
        recipients = [name for name in names if name != sender]
        for name in recipients:
            self.send(sender, name, content, "broadcast")
        return f"Broadcast to {len(recipients)} teammates"
