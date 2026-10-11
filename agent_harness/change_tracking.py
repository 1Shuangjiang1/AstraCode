"""Per-run text-file checkpoints, diffs and conflict-aware rollback."""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import atomic_write


IGNORED_PARTS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", ".next", ".idea", ".vscode", ".tasks", ".team", ".memory",
}
TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".jsonl",
    ".md", ".txt", ".rst", ".html", ".htm", ".css", ".scss", ".less", ".xml", ".svg",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt", ".kts", ".go", ".rs",
    ".sql", ".sh", ".ps1", ".bat", ".cmd", ".dockerfile", ".gitignore", ".gitattributes",
}
TEXT_NAMES = {"Dockerfile", "Makefile", "LICENSE", "README", "requirements.txt", "package-lock.json"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_text(path: Path, data: bytes) -> bool:
    if path.name in TEXT_NAMES or path.suffix.lower() in TEXT_EXTENSIONS:
        return b"\x00" not in data[:4096]
    if b"\x00" in data[:4096]:
        return False
    try:
        data[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


@dataclass
class SnapshotFile:
    path: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


class RunTransaction:
    """Snapshot text files for one user run without touching git state."""

    def __init__(self, storage_dir: Path, request_id: str, *, max_file_bytes: int = 2_000_000,
                 max_files: int = 5000, max_total_bytes: int = 120_000_000):
        self.storage_dir = storage_dir.resolve() / "transactions" / request_id
        self.before_dir = self.storage_dir / "before"
        self.manifest_path = self.storage_dir / "manifest.json"
        self.request_id = request_id
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self.root: Path | None = None
        self.before: dict[str, SnapshotFile] = {}
        self.started = False
        self.result: dict[str, Any] | None = None

    def _paths(self, root: Path):
        count = 0
        for path in root.rglob("*"):
            if count >= self.max_files:
                break
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            count += 1
            yield path, relative

    def _scan(self, root: Path, *, backup: bool = False) -> tuple[dict[str, SnapshotFile], list[str]]:
        found: dict[str, SnapshotFile] = {}
        skipped: list[str] = []
        total = 0
        for path, relative in self._paths(root):
            key = relative.as_posix()
            try:
                size = path.stat().st_size
                if size > self.max_file_bytes or total + size > self.max_total_bytes:
                    skipped.append(key)
                    continue
                data = path.read_bytes()
                if not _is_text(path, data):
                    continue
                total += len(data)
                found[key] = SnapshotFile(key, _sha(data), len(data))
                if backup:
                    target = self.before_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            except (OSError, ValueError):
                skipped.append(key)
        return found, skipped

    def begin(self, root: Path) -> dict[str, Any]:
        if self.started:
            return {"started": True, "root": str(self.root), "files": len(self.before)}
        root = root.resolve()
        if not root.is_dir():
            raise ValueError(f"Transaction root is not a directory: {root}")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.before_dir.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.before, skipped = self._scan(root, backup=True)
        self.started = True
        atomic_write(self.manifest_path, json.dumps({
            "request_id": self.request_id, "root": str(root), "state": "started",
            "before": {key: value.as_dict() for key, value in self.before.items()},
            "skipped": skipped,
        }, ensure_ascii=False, indent=2))
        return {"started": True, "root": str(root), "files": len(self.before), "skipped": skipped}

    @staticmethod
    def _decode(data: bytes) -> str:
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _line_stats(before: str, after: str) -> tuple[int, int]:
        additions = deletions = 0
        for line in difflib.ndiff(before.splitlines(), after.splitlines()):
            if line.startswith("+ "):
                additions += 1
            elif line.startswith("- "):
                deletions += 1
        return additions, deletions

    def finish(self) -> dict[str, Any]:
        if not self.started or not self.root:
            self.result = {"id": self.request_id, "state": "empty", "files": [], "manifest_path": str(self.manifest_path), "totals": {"files": 0, "additions": 0, "deletions": 0}}
            return self.result
        after, skipped = self._scan(self.root, backup=False)
        changes = []
        total_add = total_del = 0
        for key in sorted(set(self.before) | set(after)):
            old = self.before.get(key)
            new = after.get(key)
            if old and new and old.sha256 == new.sha256:
                continue
            if old and new:
                status = "modified"
            elif new:
                status = "created"
            else:
                status = "deleted"
            before_data = (self.before_dir / Path(key)).read_bytes() if old else b""
            after_path = self.root / Path(key)
            after_data = after_path.read_bytes() if new and after_path.exists() else b""
            before_text, after_text = self._decode(before_data), self._decode(after_data)
            additions, deletions = self._line_stats(before_text, after_text)
            diff = "\n".join(difflib.unified_diff(
                before_text.splitlines(), after_text.splitlines(),
                fromfile=f"a/{key}", tofile=f"b/{key}", lineterm="",
            ))
            change = {
                "path": key, "status": status, "additions": additions, "deletions": deletions,
                "before_sha256": old.sha256 if old else None,
                "after_sha256": new.sha256 if new else None,
                "before_size": old.size if old else 0, "after_size": new.size if new else 0,
                "diff": diff[:240000],
                "before_preview": before_text[:120000], "after_preview": after_text[:120000],
            }
            changes.append(change); total_add += additions; total_del += deletions
        self.result = {
            "id": self.request_id, "root": str(self.root), "state": "ready", "files": changes,
            "manifest_path": str(self.manifest_path),
            "totals": {"files": len(changes), "additions": total_add, "deletions": total_del,
                       "created": sum(item["status"] == "created" for item in changes),
                       "modified": sum(item["status"] == "modified" for item in changes),
                       "deleted": sum(item["status"] == "deleted" for item in changes)},
            "skipped": sorted(set(skipped)),
        }
        manifest = {**self.result, "before": {key: value.as_dict() for key, value in self.before.items()}}
        atomic_write(self.manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
        return self.result

    def rollback(self) -> dict[str, Any]:
        if not self.result:
            self.finish()
        assert self.result is not None
        restored: list[str] = []
        conflicts: list[str] = []
        if not self.root:
            return {"ok": True, "restored": [], "conflicts": []}
        for change in self.result.get("files", []):
            relative = Path(str(change["path"]))
            target = (self.root / relative).resolve()
            if not target.is_relative_to(self.root):
                conflicts.append(str(relative)); continue
            current_sha = _sha(target.read_bytes()) if target.is_file() else None
            if current_sha != change.get("after_sha256"):
                conflicts.append(str(relative)); continue
            if change["status"] == "created":
                target.unlink(missing_ok=True)
            else:
                backup = self.before_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            restored.append(str(change["path"]))
        self.result["state"] = "rolled_back" if not conflicts else "rollback_partial"
        self.result["rollback"] = {"restored": restored, "conflicts": conflicts}
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8")) if self.manifest_path.exists() else {}
        manifest.update({"state": self.result["state"], "rollback": self.result["rollback"]})
        atomic_write(self.manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
        return {"ok": not conflicts, "restored": restored, "conflicts": conflicts, "state": self.result["state"]}

    @classmethod
    def load(cls, manifest_path: Path) -> "RunTransaction":
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        storage_dir = manifest_path.parent.parent.parent
        instance = cls(storage_dir, str(data["id"] if "id" in data else data["request_id"]))
        instance.storage_dir = manifest_path.parent
        instance.before_dir = instance.storage_dir / "before"
        instance.manifest_path = manifest_path
        instance.root = Path(data["root"]).resolve()
        instance.before = {key: SnapshotFile(**value) for key, value in (data.get("before") or {}).items()}
        instance.started = True
        instance.result = {key: value for key, value in data.items() if key != "before"}
        return instance
