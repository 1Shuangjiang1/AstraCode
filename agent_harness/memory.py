from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .state import atomic_write
from .ui import Console, text_content


class MemoryStore:
    TYPES = {"user", "feedback", "project", "reference"}

    def __init__(self, directory: Path, client, model: str, console: Console, consolidate_threshold: int = 10):
        self.directory = directory
        self.index_path = directory / "MEMORY.md"
        self.client = client
        self.model = model
        self.console = console
        self.consolidate_threshold = consolidate_threshold
        self._lock = threading.RLock()

    @staticmethod
    def _frontmatter(text: str) -> tuple[dict, str]:
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        meta = {}
        for line in parts[1].strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip("\"'")
        return meta, parts[2].strip()

    @staticmethod
    def _slug(name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", name.lower()).strip("-") or f"memory-{int(time.time())}"

    def list_data(self) -> list[dict]:
        with self._lock:
            if not self.directory.exists():
                return []
            result = []
            for path in sorted(self.directory.glob("*.md")):
                if path.name == self.index_path.name:
                    continue
                meta, body = self._frontmatter(path.read_text(encoding="utf-8"))
                result.append({"filename": path.name, "name": meta.get("name", path.stem),
                               "description": meta.get("description", ""),
                               "type": meta.get("type", "user"), "body": body})
            return result

    def rebuild_index(self):
        lines = [f"- [{item['name']}]({item['filename']}) - {item['description']}" for item in self.list_data()]
        atomic_write(self.index_path, "\n".join(lines) + ("\n" if lines else ""))

    def write(self, name: str, memory_type: str, description: str, body: str):
        memory_type = memory_type if memory_type in self.TYPES else "user"
        content = f"---\nname: {name}\ndescription: {description}\ntype: {memory_type}\n---\n\n{body}\n"
        with self._lock:
            atomic_write(self.directory / f"{self._slug(name)}.md", content)
            self.rebuild_index()

    def index(self) -> str:
        with self._lock:
            return self.index_path.read_text(encoding="utf-8").strip() if self.index_path.exists() else ""

    @staticmethod
    def _recent_user_text(messages: list, limit: int = 2000) -> str:
        recent = []
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, str):
                recent.append(content)
            if len(recent) >= 3:
                break
        return " ".join(reversed(recent))[:limit]

    @staticmethod
    def _json_array(text: str) -> list:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        return json.loads(match.group()) if match else []

    def select(self, messages: list, max_items: int = 5) -> list[dict]:
        files, recent = self.list_data(), self._recent_user_text(messages)
        if not files or not recent:
            return []
        catalog = "\n".join(f"{i}: {item['name']} - {item['description']}" for i, item in enumerate(files))
        prompt = ("Select clearly relevant memory indices. Return ONLY a JSON array of integers.\n\n"
                  f"Recent conversation:\n{recent}\n\nMemory catalog:\n{catalog}")
        try:
            response = self.client.messages.create(model=self.model,
                messages=[{"role": "user", "content": prompt}], max_tokens=200)
            indices = self._json_array(text_content(response.content))
            return [files[index] for index in indices if isinstance(index, int) and 0 <= index < len(files)][:max_items]
        except Exception as exc:
            self.console.log("Memory", "相关记忆选择失败，使用关键词降级", str(exc), "yellow")
            words = {word.lower() for word in re.findall(r"[a-zA-Z0-9_]{4,}", recent)}
            return [item for item in files if any(word in f"{item['name']} {item['description']}".lower()
                                                  for word in words)][:max_items]

    def relevant_xml(self, messages: list) -> str:
        selected = self.select(messages)
        if not selected:
            return ""
        bodies = []
        for item in selected:
            path = (self.directory / item["filename"]).resolve()
            if path.is_relative_to(self.directory.resolve()) and path.exists():
                bodies.append(path.read_text(encoding="utf-8"))
        return "<relevant_memories>\n" + "\n\n".join(bodies) + "\n</relevant_memories>"

    @staticmethod
    def _dialogue(messages: list) -> str:
        lines = []
        for message in messages[-10:]:
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                lines.append(f"{message.get('role', '?')}: {content}")
            elif isinstance(content, list):
                text = text_content(content)
                if text.strip():
                    lines.append(f"{message.get('role', '?')}: {text}")
        return "\n".join(lines)

    def extract(self, messages: list):
        dialogue = self._dialogue(messages)
        if not dialogue:
            return
        existing = "\n".join(f"- {item['name']}: {item['description']}" for item in self.list_data()) or "(none)"
        prompt = ("Extract durable preferences, constraints, feedback, or project facts. Return a JSON array "
                  "of {name,type,description,body}; return [] when nothing is new.\n\n"
                  f"Existing:\n{existing}\n\nDialogue:\n{dialogue[:4000]}")
        try:
            response = self.client.messages.create(model=self.model,
                messages=[{"role": "user", "content": prompt}], max_tokens=800)
            items = self._json_array(text_content(response.content))
            for item in items:
                if item.get("description") and item.get("body"):
                    self.write(item.get("name", "memory"), item.get("type", "user"),
                               item["description"], item["body"])
        except Exception as exc:
            self.console.log("Memory", "记忆提取失败，不影响主任务", str(exc), "yellow")

    def consolidate(self):
        files = self.list_data()
        if len(files) < self.consolidate_threshold:
            return
        catalog = "\n\n".join(json.dumps(item, ensure_ascii=False) for item in files)
        prompt = "Merge duplicate/outdated memories. Return JSON array of {name,type,description,body}.\n\n" + catalog[:16000]
        try:
            response = self.client.messages.create(model=self.model,
                messages=[{"role": "user", "content": prompt}], max_tokens=3000)
            items = self._json_array(text_content(response.content))
            if not items:
                return
            replacement = self.directory.with_name(self.directory.name + ".next")
            replacement.mkdir(parents=True, exist_ok=True)
            staged = MemoryStore(replacement, self.client, self.model, self.console, self.consolidate_threshold)
            for item in items:
                if item.get("description") and item.get("body"):
                    staged.write(item.get("name", "memory"), item.get("type", "user"),
                                 item["description"], item["body"])
            with self._lock:
                backup = self.directory.with_name(self.directory.name + ".backup")
                if backup.exists():
                    for path in backup.glob("*"):
                        path.unlink()
                    backup.rmdir()
                self.directory.rename(backup)
                replacement.rename(self.directory)
        except Exception as exc:
            self.console.log("Memory", "记忆合并失败，旧记忆保持不变", str(exc), "yellow")
