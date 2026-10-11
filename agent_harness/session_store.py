from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .message_protocol import repair_tool_protocol


SCHEMA_VERSION = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_data_dir() -> Path:
    configured = os.getenv("S_FULL_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.getenv("LOCALAPPDATA", "").strip()
    return (Path(local) / "s_full" if local else Path.home() / ".s_full").resolve()


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return json_value(value.dict())
    result = {key: json_value(item) for key, item in vars(value).items() if not key.startswith("_")} if hasattr(value, "__dict__") else None
    return result if result else str(value)


def safe_component(value: str) -> str:
    """Keep diagnostic paths inside the application data directory."""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return normalized[:120] or "unknown"


class SessionStore:
    """Thread-safe local persistence for projects, conversations, model context and audit events."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or default_data_dir()).resolve()
        self.sessions_dir = self.data_dir / "sessions"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "index.sqlite"
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    settings_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE UNIQUE INDEX IF NOT EXISTS projects_path_key ON projects(path COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    workspace_key TEXT NOT NULL,
                    project_id TEXT,
                    workspace_mode TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'idle',
                    model TEXT,
                    permission TEXT,
                    thinking_effort TEXT,
                    project_path TEXT,
                    active_directory TEXT,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    summary_updated_at TEXT,
                    context_tokens INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    ui_state_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_workspace_order ON sessions(workspace_key, archived, pinned DESC, updated_at DESC);

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS messages_session_order ON messages(session_id, position);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS events_session_order ON events(session_id, id);

                CREATE TABLE IF NOT EXISTS model_state (
                    session_id TEXT PRIMARY KEY,
                    history_json TEXT NOT NULL DEFAULT '[]',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL,
                    title TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS plans_session_order ON plans(session_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS runs (
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_request_id TEXT,
                    state TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    checkpoint_json TEXT NOT NULL DEFAULT '{}',
                    change_set_json TEXT NOT NULL DEFAULT '{}',
                    verification_json TEXT NOT NULL DEFAULT '{}',
                    recoverable INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS runs_session_order ON runs(session_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            # A fresh sidecar cannot still own an unfinished thread. Preserve it as
            # recoverable instead of converting it into an opaque error.
            now = utc_now()
            self._connection.execute(
                "UPDATE runs SET state='interrupted',phase='interrupted',recoverable=1,updated_at=?,error=COALESCE(error,'Application stopped before a terminal event') WHERE state IN ('queued','running','verifying','remediating')",
                (now,),
            )
            self._connection.execute("UPDATE sessions SET status='interrupted' WHERE status='running'")

    @staticmethod
    def _session_columns(session: dict[str, Any]) -> tuple[Any, ...]:
        now = utc_now()
        workspace_key = str(session.get("workspaceKey") or "chat")
        project_id = workspace_key.split(":", 1)[1] if workspace_key.startswith("project:") else None
        return (
            str(session["id"]), workspace_key, project_id,
            "project" if project_id else "chat", str(session.get("title") or "新对话"),
            str(session.get("createdAt") or now), str(session.get("updatedAt") or now),
            str(session.get("status") or "idle"), session.get("model"), session.get("permission"),
            session.get("thinkingEffort"), session.get("projectPath"), session.get("activeDirectory"),
            int(bool(session.get("pinned"))), int(bool(session.get("archived"))),
            str(session.get("summary") or ""), session.get("summaryUpdatedAt"),
            int(session.get("contextTokens") or 0), int(session.get("schemaVersion") or SCHEMA_VERSION),
            json.dumps({
                "timeline": json_value(session.get("timeline") or []),
                "todos": json_value(session.get("todos") or []),
                "agents": json_value(session.get("agents") or []),
                "changeSet": json_value(session.get("changeSet") or {}),
                "verification": json_value(session.get("verification") or {}),
            }, ensure_ascii=False),
        )

    def save_library(self, projects: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self._lock, self._connection:
            for project in projects:
                self._connection.execute(
                    """INSERT INTO projects(id,name,path,created_at,updated_at,settings_json)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name,path=excluded.path,updated_at=excluded.updated_at""",
                    (str(project["id"]), str(project.get("name") or "项目"), str(project.get("path") or ""),
                     str(project.get("createdAt") or now), now, json.dumps(project.get("settings") or {}, ensure_ascii=False)),
                )
            for session in sessions:
                self._upsert_session_locked(session)

    def _upsert_session_locked(self, session: dict[str, Any]) -> None:
        columns = list(self._session_columns(session))
        if columns[2] and not self._connection.execute("SELECT 1 FROM projects WHERE id=?", (columns[2],)).fetchone():
            columns[2] = None
        self._connection.execute(
            """INSERT INTO sessions(
                id,workspace_key,project_id,workspace_mode,title,created_at,updated_at,status,model,permission,
                thinking_effort,project_path,active_directory,pinned,archived,summary,summary_updated_at,
                context_tokens,schema_version,ui_state_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                workspace_key=excluded.workspace_key,project_id=excluded.project_id,workspace_mode=excluded.workspace_mode,
                title=excluded.title,updated_at=excluded.updated_at,status=excluded.status,model=excluded.model,
                permission=excluded.permission,thinking_effort=excluded.thinking_effort,project_path=excluded.project_path,
                active_directory=COALESCE(excluded.active_directory,sessions.active_directory),pinned=excluded.pinned,
                archived=excluded.archived,summary=CASE WHEN excluded.summary='' THEN sessions.summary ELSE excluded.summary END,
                summary_updated_at=COALESCE(excluded.summary_updated_at,sessions.summary_updated_at),
                context_tokens=CASE WHEN excluded.context_tokens=0 THEN sessions.context_tokens ELSE excluded.context_tokens END,
                schema_version=excluded.schema_version,ui_state_json=excluded.ui_state_json""",
            columns,
        )
        session_id = str(session["id"])
        self._connection.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        for position, message in enumerate(session.get("messages") or []):
            self._connection.execute(
                "INSERT INTO messages(id,session_id,role,content,created_at,position) VALUES(?,?,?,?,?,?)",
                (str(message.get("id") or f"{session_id}-{position}"), session_id, str(message.get("role") or "assistant"),
                 str(message.get("content") or ""), str(message.get("timestamp") or utc_now()), position),
            )
        has_model_state = self._connection.execute("SELECT 1 FROM model_state WHERE session_id=?", (session_id,)).fetchone()
        if not has_model_state:
            visible = [{"role": str(item.get("role") or "assistant"), "content": str(item.get("content") or "")}
                       for item in session.get("messages") or []]
            first_user = next((index for index, item in enumerate(visible) if item["role"] == "user"), len(visible))
            visible = visible[first_user:]
            if visible:
                encoded = json.dumps(visible, ensure_ascii=False)
                self._connection.execute(
                    "INSERT INTO model_state(session_id,history_json,summary_json,token_estimate,updated_at) VALUES(?,?,?,?,?)",
                    (session_id, encoded, "{}", len(encoded) // 4, utc_now()),
                )

    def list_library(self) -> dict[str, Any]:
        with self._lock:
            projects = [dict(row) for row in self._connection.execute(
                "SELECT id,name,path,created_at AS createdAt,updated_at AS updatedAt FROM projects ORDER BY updated_at DESC"
            )]
            rows = self._connection.execute("SELECT * FROM sessions ORDER BY pinned DESC, updated_at DESC").fetchall()
            sessions = []
            for row in rows:
                ui_state = json.loads(row["ui_state_json"] or "{}")
                messages = [
                    {"id": item["id"], "role": item["role"], "content": item["content"], "timestamp": item["created_at"]}
                    for item in self._connection.execute(
                        "SELECT id,role,content,created_at FROM messages WHERE session_id=? ORDER BY position", (row["id"],)
                    )
                ]
                sessions.append({
                    "id": row["id"], "workspaceKey": row["workspace_key"], "title": row["title"],
                    "createdAt": row["created_at"], "updatedAt": row["updated_at"], "status": row["status"],
                    "model": row["model"], "permission": row["permission"], "thinkingEffort": row["thinking_effort"],
                    "projectPath": row["project_path"], "activeDirectory": row["active_directory"],
                    "pinned": bool(row["pinned"]), "archived": bool(row["archived"]),
                    "summary": row["summary"], "summaryUpdatedAt": row["summary_updated_at"],
                    "contextTokens": row["context_tokens"], "schemaVersion": row["schema_version"],
                    "messages": messages, "timeline": ui_state.get("timeline") or [],
                    "todos": ui_state.get("todos") or [], "agents": ui_state.get("agents") or [],
                    "changeSet": ui_state.get("changeSet") or None,
                    "verification": ui_state.get("verification") or None,
                    "plan": self.get_latest_plan(row["id"]),
                })
            return {"projects": projects, "conversations": sessions, "dataPath": str(self.path), "schemaVersion": SCHEMA_VERSION}

    def ensure_session(self, session_id: str, workspace_key: str = "chat", **metadata: Any) -> None:
        now = utc_now()
        session = {
            "id": session_id, "workspaceKey": workspace_key, "title": metadata.get("title", "新对话"),
            "createdAt": metadata.get("created_at", now), "updatedAt": now, "status": metadata.get("status", "idle"),
            "model": metadata.get("model"), "permission": metadata.get("permission"),
            "thinkingEffort": metadata.get("thinking_effort"), "projectPath": metadata.get("project_path"),
            "messages": [], "timeline": [],
        }
        with self._lock, self._connection:
            exists = self._connection.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not exists:
                self._upsert_session_locked(session)

    def append_event(self, event: dict[str, Any]) -> None:
        session_id = str(event.get("session_id") or "")
        if not session_id:
            return
        created_at = str(event.get("timestamp") or utc_now())
        payload = json.dumps(json_value(event), ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connection:
            exists = self._connection.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not exists:
                self.ensure_session(session_id)
            self._connection.execute(
                "INSERT INTO events(session_id,event_type,created_at,payload_json) VALUES(?,?,?,?)",
                (session_id, str(event.get("type") or "event"), created_at, payload),
            )
            event_type = str(event.get("type") or "event")
            status = {"session_started": "running", "task_completed": "completed", "task_incomplete": "error", "task_cancelled": "cancelled", "task_interrupted": "interrupted", "error": "error"}.get(event_type)
            if status:
                self._connection.execute("UPDATE sessions SET updated_at=?,status=? WHERE id=?", (created_at, status, session_id))
            else:
                self._connection.execute("UPDATE sessions SET updated_at=? WHERE id=?", (created_at, session_id))
            if event_type == "assistant_message" and event.get("content"):
                self._append_message_locked(
                    session_id, "assistant", str(event["content"]), created_at,
                    f"{session_id}-{created_at}",
                )
            request_id = str(event.get("request_id") or "")
            run = self._connection.execute("SELECT checkpoint_json FROM runs WHERE request_id=?", (request_id,)).fetchone() if request_id else None
            if run:
                checkpoint = json.loads(run["checkpoint_json"] or "{}")
                checkpoint["last_event"] = event_type
                checkpoint["last_event_at"] = created_at
                if event_type == "tool_started":
                    checkpoint["pending_tool"] = {
                        "tool_id": event.get("tool_id"), "tool": event.get("tool"),
                        "detail": event.get("detail"), "started_at": created_at,
                    }
                elif event_type == "tool_completed":
                    pending = checkpoint.get("pending_tool") or {}
                    if not event.get("tool_id") or pending.get("tool_id") == event.get("tool_id"):
                        checkpoint["pending_tool"] = None
                    completed = list(checkpoint.get("completed_tools") or [])
                    completed.append({"tool": event.get("tool"), "ok": event.get("ok"), "at": created_at})
                    checkpoint["completed_tools"] = completed[-100:]
                run_state, phase, recoverable, finished = None, None, None, False
                if event_type == "session_started": run_state, phase = "running", "connecting"
                elif event_type == "status": run_state, phase = "running", str(event.get("phase") or "executing")
                elif event_type == "verification_started": run_state, phase = "verifying", "verifying"
                elif event_type == "verification_remediation_started": run_state, phase = "remediating", "remediating"
                elif event_type == "task_completed": run_state, phase, recoverable, finished = "completed", "completed", False, True
                elif event_type == "task_incomplete": run_state, phase, recoverable, finished = "failed", "failed", False, True
                elif event_type == "task_cancelled": run_state, phase, recoverable, finished = "cancelled", "interrupted", True, True
                elif event_type == "task_interrupted": run_state, phase, recoverable = "interrupted", "interrupted", True
                elif event_type == "error": run_state, phase, recoverable = "interrupted", "interrupted", True
                fields = ["checkpoint_json=?", "updated_at=?"]
                values: list[Any] = [json.dumps(checkpoint, ensure_ascii=False), created_at]
                if run_state is not None: fields.append("state=?"); values.append(run_state)
                if phase is not None: fields.append("phase=?"); values.append(phase)
                if recoverable is not None: fields.append("recoverable=?"); values.append(int(recoverable))
                if finished: fields.append("finished_at=?"); values.append(created_at)
                values.append(request_id)
                self._connection.execute(f"UPDATE runs SET {','.join(fields)} WHERE request_id=?", values)
        event_dir = self.sessions_dir / safe_component(session_id)
        event_dir.mkdir(parents=True, exist_ok=True)
        with (event_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        request_id = str(event.get("request_id") or "")
        if request_id:
            run_path = self.run_log_path(session_id, request_id)
            run_path.parent.mkdir(parents=True, exist_ok=True)
            with run_path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")

    def run_log_path(self, session_id: str, request_id: str) -> Path:
        return self.sessions_dir / safe_component(session_id) / "runs" / f"{safe_component(request_id)}.jsonl"

    def runtime_dir(self, session_id: str) -> Path:
        return self.sessions_dir / safe_component(session_id) / "runtime"

    def create_run(self, request_id: str, session_id: str, prompt: str, config: dict[str, Any],
                   parent_request_id: str | None = None) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR REPLACE INTO runs(
                       request_id,session_id,parent_request_id,state,phase,prompt,config_json,
                       checkpoint_json,change_set_json,verification_json,recoverable,error,
                       started_at,updated_at,finished_at)
                   VALUES(?,?,?,'queued','queued',? ,?,'{}','{}','{}',0,NULL,?,?,NULL)""",
                (request_id, session_id, parent_request_id, prompt,
                 json.dumps(json_value(config), ensure_ascii=False), now, now),
            )

    def update_run(self, request_id: str, *, state: str | None = None, phase: str | None = None,
                   checkpoint: dict[str, Any] | None = None, change_set: dict[str, Any] | None = None,
                   verification: dict[str, Any] | None = None, recoverable: bool | None = None,
                   error: str | None = None, finished: bool = False) -> bool:
        fields, values = ["updated_at=?"], [utc_now()]
        for column, value in (("state", state), ("phase", phase), ("error", error)):
            if value is not None:
                fields.append(f"{column}=?"); values.append(value)
        for column, value in (("checkpoint_json", checkpoint), ("change_set_json", change_set), ("verification_json", verification)):
            if value is not None:
                fields.append(f"{column}=?"); values.append(json.dumps(json_value(value), ensure_ascii=False))
        if recoverable is not None:
            fields.append("recoverable=?"); values.append(int(recoverable))
        if finished:
            fields.append("finished_at=?"); values.append(utc_now())
        values.append(request_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(f"UPDATE runs SET {','.join(fields)} WHERE request_id=?", values)
            return cursor.rowcount > 0

    @staticmethod
    def _run_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "request_id": row["request_id"], "session_id": row["session_id"],
            "parent_request_id": row["parent_request_id"], "state": row["state"], "phase": row["phase"],
            "prompt": row["prompt"], "config": json.loads(row["config_json"] or "{}"),
            "checkpoint": json.loads(row["checkpoint_json"] or "{}"),
            "change_set": json.loads(row["change_set_json"] or "{}"),
            "verification": json.loads(row["verification_json"] or "{}"),
            "recoverable": bool(row["recoverable"]), "error": row["error"],
            "started_at": row["started_at"], "updated_at": row["updated_at"], "finished_at": row["finished_at"],
        }

    def get_run(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM runs WHERE request_id=?", (request_id,)).fetchone()
        return self._run_row(row)

    def list_recoverable_runs(self, session_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs WHERE recoverable=1"
        values: tuple[Any, ...] = ()
        if session_id:
            query += " AND session_id=?"; values = (session_id,)
        query += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return [self._run_row(row) for row in rows if row is not None]

    def clear_recovery(self, request_id: str) -> bool:
        return self.update_run(request_id, recoverable=False)

    def _append_message_locked(self, session_id: str, role: str, content: str, created_at: str, message_id: str) -> None:
        position = self._connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM messages WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        self._connection.execute(
            "INSERT OR IGNORE INTO messages(id,session_id,role,content,created_at,position) VALUES(?,?,?,?,?,?)",
            (message_id, session_id, role, content, created_at, position),
        )

    def append_message(self, session_id: str, role: str, content: str,
                       created_at: str | None = None, message_id: str | None = None) -> None:
        created_at = created_at or utc_now()
        message_id = message_id or f"{session_id}-{created_at}-{role}"
        with self._lock, self._connection:
            self._append_message_locked(session_id, role, content, created_at, message_id)
            if role == "user":
                self._connection.execute(
                    "UPDATE sessions SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=? WHERE id=?",
                    (content[:24], created_at, session_id),
                )

    def should_generate_title(self, session_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT s.title,
                          (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id AND m.role='user') AS user_count
                   FROM sessions s WHERE s.id=?""",
                (session_id,),
            ).fetchone()
        return bool(row and int(row["user_count"] or 0) == 1)

    def update_session_title(self, session_id: str, title: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(title or "")).strip()[:40]
        if not normalized:
            return False
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE sessions SET title=?,updated_at=? WHERE id=?",
                (normalized, utc_now(), session_id),
            )
            return cursor.rowcount > 0

    def load_model_state(self, session_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT history_json,summary_json FROM model_state WHERE session_id=?", (session_id,)
            ).fetchone()
        if not row:
            return [], {}
        return json.loads(row["history_json"] or "[]"), json.loads(row["summary_json"] or "{}")

    def save_model_state(self, session_id: str, history: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> None:
        normalized = json_value(history)
        repair_tool_protocol(normalized)
        token_estimate = len(json.dumps(normalized, ensure_ascii=False)) // 4
        summary_value = json_value(summary or {})
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO model_state(session_id,history_json,summary_json,token_estimate,updated_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                   history_json=excluded.history_json,summary_json=CASE WHEN excluded.summary_json='{}' THEN model_state.summary_json ELSE excluded.summary_json END,
                   token_estimate=excluded.token_estimate,updated_at=excluded.updated_at""",
                (session_id, json.dumps(normalized, ensure_ascii=False), json.dumps(summary_value, ensure_ascii=False), token_estimate, now),
            )
            summary_text = str(summary_value.get("summary") or "") if isinstance(summary_value, dict) else ""
            self._connection.execute(
                """UPDATE sessions SET context_tokens=?,summary=CASE WHEN ?='' THEN summary ELSE ? END,
                   summary_updated_at=CASE WHEN ?='' THEN summary_updated_at ELSE ? END,updated_at=? WHERE id=?""",
                (token_estimate, summary_text, summary_text, summary_text, now, now, session_id),
            )

    def save_plan(self, session_id: str, plan: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
        now = utc_now()
        encoded = json.dumps(json_value(plan), ensure_ascii=False)
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO plans(id,session_id,revision,state,title,request_text,plan_json,metadata_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                   revision=excluded.revision,state=excluded.state,title=excluded.title,
                   request_text=excluded.request_text,plan_json=excluded.plan_json,
                   metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                (str(plan["id"]), session_id, int(plan.get("revision") or 1), str(plan.get("state") or "planning"),
                 str(plan.get("title") or "执行计划"), str(plan.get("request") or ""), encoded,
                 json.dumps(json_value(metadata or {}), ensure_ascii=False), now, now),
            )

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            return None
        plan = json.loads(row["plan_json"] or "{}")
        plan["metadata"] = json.loads(row["metadata_json"] or "{}")
        plan["session_id"] = row["session_id"]
        return plan

    def get_latest_plan(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM plans WHERE session_id=? ORDER BY revision DESC,updated_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self.get_plan(row["id"]) if row else None

    def update_plan_state(self, plan_id: str, state: str, *, steps: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        plan["state"] = state
        if steps is not None:
            plan["steps"] = steps
        metadata = plan.pop("metadata", {})
        session_id = str(plan.pop("session_id"))
        self.save_plan(session_id, plan, metadata)
        plan["metadata"] = metadata
        plan["session_id"] = session_id
        return plan

    def update_session_state(self, session_id: str, *, pinned: bool | None = None, archived: bool | None = None) -> bool:
        assignments, values = [], []
        if pinned is not None:
            assignments.append("pinned=?")
            values.append(int(pinned))
        if archived is not None:
            assignments.append("archived=?")
            values.append(int(archived))
        if not assignments:
            return False
        assignments.append("updated_at=?")
        values.append(utc_now())
        values.append(session_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(f"UPDATE sessions SET {','.join(assignments)} WHERE id=?", values)
            return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        directory = self.sessions_dir / safe_component(session_id)
        if directory.exists() and directory.parent == self.sessions_dir:
            shutil.rmtree(directory)
        return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()
