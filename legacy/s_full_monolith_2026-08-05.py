#!/usr/bin/env python3
# Harness: all mechanisms combined -- the complete cockpit for the model.
"""
s_full.py - Full Reference Agent

Capstone implementation combining every mechanism from s01-s11.
Session s12 (task-aware worktree isolation) is taught separately.
NOT a teaching session -- this is the "put it all together" reference.

    +------------------------------------------------------------------+
    |                        FULL AGENT                                 |
    |                                                                   |
    |  System prompt (s05 skills, task-first + optional todo nag)      |
    |                                                                   |
    |  Before each LLM call:                                            |
    |  +--------------------+  +------------------+  +--------------+  |
    |  | Microcompact (s06) |  | Drain bg (s08)   |  | Check inbox  |  |
    |  | Auto-compact (s06) |  | notifications    |  | (s09)        |  |
    |  +--------------------+  +------------------+  +--------------+  |
    |                                                                   |
    |  Tool dispatch (s02 pattern):                                     |
    |  +--------+----------+----------+---------+-----------+          |
    |  | bash   | read     | write    | edit    | TodoWrite |          |
    |  | task   | load_sk  | compress | bg_run  | bg_check  |          |
    |  | t_crt  | t_get    | t_upd    | t_list  | spawn_tm  |          |
    |  | list_tm| send_msg | rd_inbox | bcast   | shutdown  |          |
    |  | plan   | idle     | claim    |         |           |          |
    |  +--------+----------+----------+---------+-----------+          |
    |                                                                   |
    |  Subagent (s04):  spawn -> work -> return summary                 |
    |  Teammate (s09):  spawn -> work -> idle -> auto-claim (s11)      |
    |  Shutdown (s10):  request_id handshake                            |
    |  Plan gate (s10): submit -> approve/reject                        |
    +------------------------------------------------------------------+

    REPL commands: /compact /tasks /team /inbox
"""

import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from queue import Queue

from anthropic import Anthropic
from dotenv import load_dotenv

for _env_path in (Path(__file__).with_name(".env"), Path.cwd() / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
load_dotenv(override=True)
# if os.getenv("ANTHROPIC_BASE_URL"):
#     os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

_client_kwargs = {"base_url": os.getenv("ANTHROPIC_BASE_URL") or None}
_client_kwargs["timeout"] = float(os.getenv("S_FULL_API_TIMEOUT", "120"))
if os.getenv("ANTHROPIC_AUTH_TOKEN"):
    _client_kwargs["auth_token"] = os.getenv("ANTHROPIC_AUTH_TOKEN")
elif os.getenv("ANTHROPIC_API_KEY"):
    _client_kwargs["api_key"] = os.getenv("ANTHROPIC_API_KEY")

client = Anthropic(**_client_kwargs)
WORKDIR = Path.cwd()
MODEL = os.getenv("S_FULL_MODEL") or os.getenv("MODEL_ID") or "deepseek-ai/DeepSeek-V4-Pro"

WORKDIR = Path.cwd()
# client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
# MODEL = os.environ["MODEL_ID"]

TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / ".tasks"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
TOKEN_THRESHOLD = 100000
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
VISUAL = os.getenv("S_FULL_VISUAL", "1").lower() not in ("0", "false", "off")
TRACE_INPUT_LIMIT = int(os.getenv("S_FULL_TRACE_INPUT_LIMIT", "900"))
TRACE_OUTPUT_LIMIT = int(os.getenv("S_FULL_TRACE_OUTPUT_LIMIT", "1200"))

VALID_MSG_TYPES = {"message", "broadcast", "shutdown_request",
                   "shutdown_response", "plan_approval_response"}

PRINT_LOCK = threading.Lock()
COLORS = {
    "reset": "\033[0m",
    "dim": "\033[90m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "magenta": "\033[35m",
    "red": "\033[31m",
    "blue": "\033[34m",
}


def _c(name: str) -> str:
    return COLORS.get(name, "") if VISUAL else ""


def preview(value, limit: int = TRACE_OUTPUT_LIMIT) -> str:
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str, indent=2)
        except TypeError:
            value = str(value)
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...（还有 {len(value) - limit} 个字符未显示）"


def visual_log(stage: str, message: str = "", detail=None,
               color: str = "cyan", force: bool = False):
    if not VISUAL and not force:
        return
    ts = time.strftime("%H:%M:%S")
    title = f"{_c(color)}[{ts}] {stage:<14}{_c('reset')}"
    if message:
        title += f" {message}"
    with PRINT_LOCK:
        print(title)
        if detail is not None:
            text = preview(detail)
            for line in text.splitlines() or [""]:
                print(f"{_c('dim')}    {line}{_c('reset')}")


def visual_banner():
    if not VISUAL:
        return
    print(f"{_c('cyan')}+{'-' * 70}+{_c('reset')}")
    print(f"{_c('cyan')}| s_full 中文可视化追踪已开启{' ' * 36}|{_c('reset')}")
    print(f"{_c('cyan')}+{'-' * 70}+{_c('reset')}")
    print(f"  模型: {MODEL}")
    print(f"  工作目录: {WORKDIR}")
    print("  本地命令: /compact /tasks /team /inbox /visual on /visual off")
    print("  关闭方式: 设置环境变量 S_FULL_VISUAL=0，或运行时输入 /visual off\n")


TOOL_LABELS = {
    "bash": "运行 shell 命令",
    "read_file": "读取文件",
    "write_file": "写入文件",
    "edit_file": "编辑文件",
    "TodoWrite": "更新 Todo 清单",
    "task": "启动子 agent",
    "load_skill": "加载 skill",
    "compress": "压缩上下文",
    "background_run": "启动后台任务",
    "check_background": "检查后台任务",
    "task_create": "创建持久任务",
    "task_get": "读取任务详情",
    "task_update": "更新任务",
    "task_list": "列出任务",
    "spawn_teammate": "启动队友 agent",
    "list_teammates": "列出队友",
    "send_message": "发送队友消息",
    "read_inbox": "读取 lead 收件箱",
    "broadcast": "广播消息",
    "shutdown_request": "请求队友关闭",
    "plan_approval": "审批队友计划",
    "idle": "进入空闲状态",
    "claim_task": "认领任务",
}


def tool_label(name: str) -> str:
    label = TOOL_LABELS.get(name)
    return f"{name}（{label}）" if label else name


def content_blocks_summary(content) -> str:
    if not isinstance(content, list):
        return type(content).__name__
    names = []
    text_blocks = 0
    for block in content:
        if getattr(block, "type", None) == "tool_use":
            names.append(getattr(block, "name", "unknown"))
        elif getattr(block, "type", None) == "text":
            text_blocks += 1
    parts = []
    if text_blocks:
        parts.append(f"text x{text_blocks}")
    if names:
        parts.append("tools: " + ", ".join(names))
    return "; ".join(parts) or f"{len(content)} block(s)"


# === SECTION: base_tools ===
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# === SECTION: permissions (s03) ===
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]


def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Blocked: '{pattern}' is on the deny list"
    return None


def _path_escapes_workspace(path: str) -> bool:
    try:
        return not (WORKDIR / path).resolve().is_relative_to(WORKDIR)
    except Exception:
        return True


PERMISSION_RULES = [
    {
        "tools": ["write_file", "edit_file"],
        "check": lambda args: _path_escapes_workspace(args.get("path", "")),
        "message": "Writing outside workspace",
    },
    {
        "tools": ["bash", "background_run"],
        "check": lambda args: any(
            kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]
        ),
        "message": "Potentially destructive command",
    },
]


def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None


def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n{_c('yellow')}Permission check: {reason}{_c('reset')}")
    print(f"   Tool: {tool_name}({args})")
    try:
        choice = input("   Allow? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "deny"
    return "allow" if choice in ("y", "yes") else "deny"


def check_permission(tool_name: str, args: dict) -> tuple[bool, str]:
    command = args.get("command", "")
    if tool_name in ("bash", "background_run"):
        reason = check_deny_list(command)
        if reason:
            visual_log("Permission", reason, {"tool": tool_name, "args": args}, color="red")
            return False, reason

    reason = check_rules(tool_name, args)
    if reason:
        if ask_user(tool_name, args, reason) != "allow":
            visual_log("Permission", f"Denied: {reason}", {"tool": tool_name, "args": args}, color="red")
            return False, reason
        visual_log("Permission", f"Allowed: {reason}", {"tool": tool_name, "args": args}, color="yellow")

    return True, ""


# === SECTION: todos (s03) ===
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        validated, ip = [], 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            af = str(item.get("activeForm", "")).strip()
            if not content: raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not af: raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress": ip += 1
            validated.append({"content": content, "status": status, "activeForm": af})
        if len(validated) > 20: raise ValueError("Max 20 todos")
        if ip > 1: raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items: return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(item["status"], "[?]")
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        return any(item.get("status") != "completed" for item in self.items)


# === SECTION: subagent (s04) ===
def run_subagent(prompt: str, agent_type: str = "Explore") -> str:
    visual_log("子Agent", f"启动子 agent，类型：{agent_type}", prompt,
               color="magenta")
    sub_tools = [
        {"name": "bash", "description": "Run command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    ]
    if agent_type != "Explore":
        sub_tools += [
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        ]
    sub_handlers = {
        "bash": lambda **kw: run_bash(kw["command"]),
        "read_file": lambda **kw: run_read(kw["path"]),
        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    }
    sub_msgs = [{"role": "user", "content": prompt}]
    resp = None
    for round_no in range(1, 31):
        visual_log("子Agent", f"第 {round_no} 轮：调用模型",
                   f"当前消息数：{len(sub_msgs)}", color="magenta")
        resp = client.messages.create(model=MODEL, messages=sub_msgs, tools=sub_tools, max_tokens=8000)
        sub_msgs.append({"role": "assistant", "content": resp.content})
        visual_log("子Agent", f"模型返回：stop_reason={resp.stop_reason}",
                   content_blocks_summary(resp.content),
                   color="magenta")
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                h = sub_handlers.get(b.name, lambda **kw: "Unknown tool")
                visual_log("子工具", tool_label(b.name), b.input,
                           color="blue")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(h(**b.input))[:50000]})
        sub_msgs.append({"role": "user", "content": results})
    if resp:
        summary = "".join(b.text for b in resp.content if hasattr(b, "text")) or "(no summary)"
        visual_log("子Agent", "子 agent 完成，返回摘要", summary, color="green")
        return summary
    return "(subagent failed)"


# === SECTION: skills (s05) ===
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills = {}
        if skills_dir.exists():
            for f in sorted(skills_dir.rglob("SKILL.md")):
                text = f.read_text()
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    body = match.group(2).strip()
                name = meta.get("name", f.parent.name)
                self.skills[name] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        if not self.skills: return "(no skills)"
        return "\n".join(f"  - {n}: {s['meta'].get('description', '-')}" for n, s in self.skills.items())

    def load(self, name: str) -> str:
        s = self.skills.get(name)
        if not s: return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{s['body']}\n</skill>"


# === SECTION: compression (s06) ===
def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4

def microcompact(messages: list):
    indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append(part)
    if len(indices) <= 3:
        return
    for part in indices[:-3]:
        if isinstance(part.get("content"), str) and len(part["content"]) > 100:
            part["content"] = "[cleared]"

def auto_compact(messages: list) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    conv_text = json.dumps(messages, default=str)[-80000:]
    resp = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": f"Summarize for continuity:\n{conv_text}"}],
        max_tokens=2000,
    )
    summary = resp.content[0].text
    return [
        {"role": "user", "content": f"[Compressed. Transcript: {path}]\n{summary}"},
    ]


# === SECTION: file_tasks (s07) ===
class TaskManager:
    def __init__(self):
        TASKS_DIR.mkdir(exist_ok=True)

    def _next_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in TASKS_DIR.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        p = TASKS_DIR / f"task_{tid}.json"
        if not p.exists(): raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text())

    def _save(self, task: dict):
        (TASKS_DIR / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        task = {"id": self._next_id(), "subject": subject, "description": description,
                "status": "pending", "owner": None, "blockedBy": []}
        self._save(task)
        visual_log("任务系统", f"创建任务 #{task['id']}：{subject}",
                   description or "(无描述)", color="blue")
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        return json.dumps(self._load(tid), indent=2)

    def update(self, tid: int, status: str = None,
               add_blocked_by: list = None, remove_blocked_by: list = None) -> str:
        task = self._load(tid)
        if status:
            task["status"] = status
            if status == "completed":
                for f in TASKS_DIR.glob("task_*.json"):
                    t = json.loads(f.read_text())
                    if tid in t.get("blockedBy", []):
                        t["blockedBy"].remove(tid)
                        self._save(t)
            if status == "deleted":
                (TASKS_DIR / f"task_{tid}.json").unlink(missing_ok=True)
                return f"Task {tid} deleted"
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task["blockedBy"] if x not in remove_blocked_by]
        self._save(task)
        visual_log("任务系统", f"更新任务 #{tid}",
                   task, color="blue")
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        tasks = [json.loads(f.read_text()) for f in sorted(TASKS_DIR.glob("task_*.json"))]
        if not tasks: return "No tasks."
        lines = []
        for t in tasks:
            m = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{m} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        visual_log("任务系统", f"{owner} 认领任务 #{tid}",
                   task, color="blue")
        return f"Claimed task #{tid} for {owner}"


# === SECTION: background (s08) ===
class BackgroundManager:
    def __init__(self):
        self.tasks = {}
        self.notifications = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {"status": "running", "command": command, "result": None}
        visual_log("后台任务", f"启动后台任务 {tid}",
                   {"command": command, "timeout": timeout}, color="yellow")
        threading.Thread(target=self._exec, args=(tid, command, timeout), daemon=True).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        try:
            r = subprocess.run(command, shell=True, cwd=WORKDIR,
                               capture_output=True, text=True, timeout=timeout)
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[tid].update({"status": "completed", "result": output or "(no output)"})
            visual_log("后台任务", f"任务 {tid} 完成",
                       self.tasks[tid]["result"], color="green")
        except Exception as e:
            self.tasks[tid].update({"status": "error", "result": str(e)})
            visual_log("后台任务", f"任务 {tid} 失败",
                       str(e), color="red")
        self.notifications.put({"task_id": tid, "status": self.tasks[tid]["status"],
                                "result": self.tasks[tid]["result"][:500]})

    def check(self, tid: str = None) -> str:
        if tid:
            t = self.tasks.get(tid)
            return f"[{t['status']}] {t.get('result') or '(running)'}" if t else f"Unknown: {tid}"
        return "\n".join(f"{k}: [{v['status']}] {v['command'][:60]}" for k, v in self.tasks.items()) or "No bg tasks."

    def drain(self) -> list:
        notifs = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        if notifs:
            visual_log("后台任务", f"收到 {len(notifs)} 条后台完成通知",
                       notifs, color="yellow")
        return notifs


# === SECTION: messaging (s09) ===
class MessageBus:
    def __init__(self):
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        msg = {"type": msg_type, "from": sender, "content": content,
               "timestamp": time.time()}
        if extra: msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        visual_log("消息系统", f"{sender} -> {to} [{msg_type}]",
                   content, color="magenta")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists(): return []
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")
        if msgs:
            visual_log("消息系统", f"读取 {name} 收件箱：{len(msgs)} 条消息",
                       msgs, color="magenta")
        return msgs

    def broadcast(self, sender: str, content: str, names: list) -> str:
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


# === SECTION: shutdown + plan tracking (s10) ===
shutdown_requests = {}
plan_requests = {}


# === SECTION: team (s09/s11) ===
class TeammateManager:
    def __init__(self, bus: MessageBus, task_mgr: TaskManager):
        TEAM_DIR.mkdir(exist_ok=True)
        self.bus = bus
        self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = self._load()
        self.threads = {}

    def _load(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name: return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()
        visual_log("队友Agent", f"启动队友：{name}（{role}）",
                   prompt, color="magenta")
        threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True).start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()
            visual_log("队友状态", f"{name} -> {status}",
                       color="magenta")

    def _loop(self, name: str, role: str, prompt: str):
        team_name = self.config["team_name"]
        sys_prompt = (f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
                      f"Use idle when done with current work. You may auto-claim tasks.")
        messages = [{"role": "user", "content": prompt}]
        tools = [
            {"name": "bash", "description": "Run command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send message.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}}, "required": ["to", "content"]}},
            {"name": "idle", "description": "Signal no more work.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "claim_task", "description": "Claim task by ID.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
        ]
        while True:
            # -- WORK PHASE --
            visual_log("队友Agent", f"{name} 进入工作阶段",
                       color="magenta")
            for round_no in range(1, 51):
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})
                try:
                    visual_log("队友Agent", f"{name} 第 {round_no} 轮调用模型",
                               f"messages={len(messages)}", color="magenta")
                    response = client.messages.create(
                        model=MODEL, system=sys_prompt, messages=messages,
                        tools=tools, max_tokens=8000)
                except Exception:
                    visual_log("队友Agent", f"{name} 调用模型失败，关闭队友",
                               color="red")
                    self._set_status(name, "shutdown")
                    return
                messages.append({"role": "assistant", "content": response.content})
                visual_log("队友Agent", f"{name} 模型返回：stop_reason={response.stop_reason}",
                           content_blocks_summary(response.content), color="magenta")
                if response.stop_reason != "tool_use":
                    break
                results = []
                idle_requested = False
                for block in response.content:
                    if block.type == "tool_use":
                        visual_log("队友工具", f"{name} 调用 {tool_label(block.name)}",
                                   block.input, color="yellow")
                        if block.name == "idle":
                            idle_requested = True
                            output = "Entering idle phase."
                        elif block.name == "claim_task":
                            output = self.task_mgr.claim(block.input["task_id"], name)
                        elif block.name == "send_message":
                            output = self.bus.send(name, block.input["to"], block.input["content"])
                        else:
                            dispatch = {"bash": lambda **kw: run_bash(kw["command"]),
                                        "read_file": lambda **kw: run_read(kw["path"]),
                                        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
                                        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])}
                            output = dispatch.get(block.name, lambda **kw: "Unknown")(**block.input)
                        visual_log("队友结果", f"{name} 的 {block.name} 执行完成",
                                   output, color="green")
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break
            # -- IDLE PHASE: poll for messages and unclaimed tasks --
            self._set_status(name, "idle")
            visual_log("队友Agent", f"{name} 进入空闲轮询阶段",
                       f"每 {POLL_INTERVAL}s 检查消息和未认领任务，最多 {IDLE_TIMEOUT}s",
                       color="magenta")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg)})
                    resume = True
                    visual_log("队友Agent", f"{name} 收到新消息，恢复工作",
                               inbox, color="magenta")
                    break
                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    t = json.loads(f.read_text())
                    if t.get("status") == "pending" and not t.get("owner") and not t.get("blockedBy"):
                        unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    visual_log("队友Agent", f"{name} 自动认领任务 #{task['id']}",
                               task, color="blue")
                    # Identity re-injection for compressed contexts
                    if len(messages) <= 3:
                        messages.insert(0, {"role": "user", "content":
                            f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>"})
                        messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})
                    messages.append({"role": "user", "content":
                        f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>"})
                    messages.append({"role": "assistant", "content": f"Claimed task #{task['id']}. Working on it."})
                    resume = True
                    break
            if not resume:
                visual_log("队友Agent", f"{name} 空闲超时，自动关闭",
                           color="yellow")
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        if not self.config["members"]: return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]


# === SECTION: memory (s09) ===
MEMORY_TYPES = ["user", "feedback", "project", "reference"]
CONSOLIDATE_THRESHOLD = 10


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].strip()


def _memory_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or f"memory-{int(time.time())}"


def write_memory_file(name: str, mem_type: str, description: str, body: str) -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if mem_type not in MEMORY_TYPES:
        mem_type = "user"
    path = MEMORY_DIR / f"{_memory_slug(name)}.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    rebuild_memory_index()
    return path


def rebuild_memory_index():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in sorted(MEMORY_DIR.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        name = meta.get("name", path.stem)
        description = meta.get("description", body.splitlines()[0][:80] if body else "")
        lines.append(f"- [{name}]({path.name}) - {description}")
    MEMORY_INDEX.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_memory_index() -> str:
    if not MEMORY_INDEX.exists():
        return ""
    return MEMORY_INDEX.read_text(encoding="utf-8").strip()


def read_memory_file(filename: str) -> str | None:
    path = (MEMORY_DIR / filename).resolve()
    try:
        if not path.is_relative_to(MEMORY_DIR.resolve()) or not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def list_memory_files() -> list[dict]:
    if not MEMORY_DIR.exists():
        return []
    memories = []
    for path in sorted(MEMORY_DIR.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        memories.append({
            "filename": path.name,
            "name": meta.get("name", path.stem),
            "description": meta.get("description", ""),
            "type": meta.get("type", "user"),
            "body": body,
        })
    return memories


def _recent_user_text(messages: list, limit: int = 2000) -> str:
    recent = []
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            recent.append(content)
        elif isinstance(content, list):
            text = " ".join(
                str(getattr(block, "text", ""))
                for block in content
                if getattr(block, "type", None) == "text"
            )
            if text:
                recent.append(text)
        if len(recent) >= 3:
            break
    return " ".join(reversed(recent))[:limit]


def select_relevant_memories(messages: list, max_items: int = 5) -> list[str]:
    files = list_memory_files()
    recent = _recent_user_text(messages)
    if not files or not recent.strip():
        return []

    catalog = "\n".join(
        f"{idx}: {mem['name']} - {mem['description']}" for idx, mem in enumerate(files)
    )
    prompt = (
        "Given the recent conversation and memory catalog, select clearly relevant "
        "memory indices. Return ONLY a JSON array of integers, such as [0, 3]. "
        "If none are relevant, return [].\n\n"
        f"Recent conversation:\n{recent}\n\nMemory catalog:\n{catalog}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        text = response.content[0].text.strip()
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if match:
            selected = []
            for idx in json.loads(match.group()):
                if isinstance(idx, int) and 0 <= idx < len(files):
                    selected.append(files[idx]["filename"])
                    if len(selected) >= max_items:
                        break
            return selected
    except Exception:
        pass

    keywords = {word.lower() for word in re.findall(r"[a-zA-Z0-9_]{4,}", recent)}
    selected = []
    for mem in files:
        haystack = f"{mem['name']} {mem['description']}".lower()
        if any(word in haystack for word in keywords):
            selected.append(mem["filename"])
            if len(selected) >= max_items:
                break
    return selected


def load_memories(messages: list) -> str:
    selected = select_relevant_memories(messages)
    if not selected:
        return ""
    parts = ["<relevant_memories>"]
    for filename in selected:
        content = read_memory_file(filename)
        if content:
            parts.append(content)
    parts.append("</relevant_memories>")
    return "\n\n".join(parts)


def _messages_to_dialogue(messages: list) -> str:
    dialogue = []
    for msg in messages[-10:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                str(getattr(block, "text", ""))
                for block in content
                if getattr(block, "type", None) == "text"
            )
        else:
            text = str(content)
        if text.strip():
            dialogue.append(f"{role}: {text}")
    return "\n".join(dialogue)


def extract_memories(messages: list):
    dialogue = _messages_to_dialogue(messages)
    if not dialogue.strip():
        return

    existing = list_memory_files()
    existing_desc = "\n".join(
        f"- {mem['name']}: {mem['description']}" for mem in existing
    ) or "(none)"
    prompt = (
        "Extract durable user preferences, constraints, feedback, or project facts "
        "from this dialogue. Return a JSON array. Each item must be "
        "{name, type, description, body}. type must be one of user, feedback, "
        "project, reference. If nothing new or already covered, return [].\n\n"
        f"Existing memories:\n{existing_desc}\n\nDialogue:\n{dialogue[:4000]}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        text = response.content[0].text.strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return
        items = json.loads(match.group())
        count = 0
        for item in items:
            name = item.get("name", f"memory-{int(time.time())}")
            mem_type = item.get("type", "user")
            description = item.get("description", "")
            body = item.get("body", "")
            if description and body:
                write_memory_file(name, mem_type, description, body)
                count += 1
        if count:
            visual_log("Memory", f"Extracted {count} new memories", color="yellow")
    except Exception:
        pass


def consolidate_memories():
    files = list_memory_files()
    if len(files) < CONSOLIDATE_THRESHOLD:
        return

    catalog = "\n\n".join(
        f"## {mem['filename']}\nname: {mem['name']}\n"
        f"description: {mem['description']}\n{mem['body']}"
        for mem in files
    )
    prompt = (
        "Consolidate these memory files. Merge duplicates, remove outdated items, "
        "keep important user preferences, and return JSON array items with "
        "{name, type, description, body}.\n\n"
        f"{catalog[:16000]}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        text = response.content[0].text.strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return
        items = json.loads(match.group())
        for path in MEMORY_DIR.glob("*.md"):
            if path.name != "MEMORY.md":
                path.unlink()
        for item in items:
            description = item.get("description", "")
            body = item.get("body", "")
            if description and body:
                write_memory_file(
                    item.get("name", f"memory-{int(time.time())}"),
                    item.get("type", "user"),
                    description,
                    body,
                )
        visual_log("Memory", f"Consolidated {len(files)} memories into {len(items)}", color="yellow")
    except Exception:
        pass


def build_system(messages: list = None) -> str:
    index = read_memory_index()
    memory_index = f"\n\nMemories available:\n{index}" if index else ""
    relevant = load_memories(messages or [])
    relevant_memories = f"\n\n{relevant}" if relevant else ""
    return (
        f"You are a coding agent at {WORKDIR}. Use tools to solve tasks.\n"
        "All destructive operations require user approval.\n"
        "Prefer task_create/task_update/task_list for multi-step work. "
        "Use TodoWrite for short checklists.\n"
        "Use task for subagent delegation. Use load_skill for specialized knowledge.\n"
        f"Skills: {SKILLS.descriptions()}"
        f"{memory_index}\n"
        "Relevant memories may be injected below. Respect durable user preferences "
        "and project facts from memory."
        f"{relevant_memories}"
    )


# === SECTION: global_instances ===
TODO = TodoManager()
SKILLS = SkillLoader(SKILLS_DIR)
TASK_MGR = TaskManager()
BG = BackgroundManager()
BUS = MessageBus()
TEAM = TeammateManager(BUS, TASK_MGR)

# === SECTION: system_prompt ===
SYSTEM = build_system()


# === SECTION: shutdown_protocol (s10) ===
def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"

# === SECTION: plan_approval (s10) ===
def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    req = plan_requests.get(request_id)
    if not req: return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    BUS.send("lead", req["from"], feedback, "plan_approval_response",
             {"request_id": request_id, "approve": approve, "feedback": feedback})
    return f"Plan {req['status']} for '{req['from']}'"


# === SECTION: tool_dispatch (s02) ===
TOOL_HANDLERS = {
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "TodoWrite":        lambda **kw: TODO.update(kw["items"]),
    "task":             lambda **kw: run_subagent(kw["prompt"], kw.get("agent_type", "Explore")),
    "load_skill":       lambda **kw: SKILLS.load(kw["name"]),
    "compress":         lambda **kw: "Compressing...",
    "background_run":   lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
    "task_create":      lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", "")),
    "task_get":         lambda **kw: TASK_MGR.get(kw["task_id"]),
    "task_update":      lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("remove_blocked_by")),
    "task_list":        lambda **kw: TASK_MGR.list_all(),
    "spawn_teammate":   lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":   lambda **kw: TEAM.list_all(),
    "send_message":     lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":       lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":        lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"]),
    "plan_approval":    lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
    "idle":             lambda **kw: "Lead does not idle.",
    "claim_task":       lambda **kw: TASK_MGR.claim(kw["task_id"], "lead"),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "TodoWrite", "description": "Update task tracking list.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "activeForm": {"type": "string"}}, "required": ["content", "status", "activeForm"]}}}, "required": ["items"]}},
    {"name": "task", "description": "Spawn a subagent for isolated exploration or work.",
     "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}, "agent_type": {"type": "string", "enum": ["Explore", "general-purpose"]}}, "required": ["prompt"]}},
    {"name": "load_skill", "description": "Load specialized knowledge by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "compress", "description": "Manually compress conversation context.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "background_run", "description": "Run command in background thread.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}},
    {"name": "check_background", "description": "Check background task status.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
    {"name": "task_create", "description": "Create a persistent file task.",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
    {"name": "task_get", "description": "Get task details by ID.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    {"name": "task_update", "description": "Update task status or dependencies.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]}, "add_blocked_by": {"type": "array", "items": {"type": "integer"}}, "remove_blocked_by": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]}},
    {"name": "task_list", "description": "List all tasks.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "spawn_teammate", "description": "Spawn a persistent autonomous teammate.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List all teammates.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send a message to a teammate.",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read and drain the lead's inbox.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Send message to all teammates.",
     "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
    {"name": "shutdown_request", "description": "Request a teammate to shut down.",
     "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "plan_approval", "description": "Approve or reject a teammate's plan.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
    {"name": "idle", "description": "Enter idle state.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "claim_task", "description": "Claim a task from the board.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
]


# === SECTION: agent_loop ===
def agent_loop(messages: list, max_rounds: int = None, max_seconds: float = None):
    if max_rounds is None:
        max_rounds = int(os.getenv("S_FULL_MAX_ROUNDS", "8"))
    if max_seconds is None:
        max_seconds = float(os.getenv("S_FULL_MAX_SECONDS", "300"))
    deadline = time.time() + max_seconds if max_seconds > 0 else None
    rounds_without_todo = 0
    round_no = 0
    while True:
        round_no += 1
        if max_rounds > 0 and round_no > max_rounds:
            visual_log("停止", f"达到最大轮数 {max_rounds}，结束当前任务", color="yellow")
            return
        if deadline is not None and time.time() > deadline:
            visual_log("停止", f"达到最大耗时 {max_seconds:.0f}s，结束当前任务", color="yellow")
            return
        pre_compact = list(messages)
        visual_log("主循环", f"第 {round_no} 轮开始：整理上下文",
                   {
                       "消息条数": len(messages),
                       "估算 token": estimate_tokens(messages),
                       "Todo 未完成": TODO.has_open_items(),
                   }, color="cyan")
        # s06: compression pipeline
        microcompact(messages)
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            visual_log("上下文压缩", "上下文超过阈值，开始自动压缩",
                       f"阈值：{TOKEN_THRESHOLD}", color="yellow")
            messages[:] = auto_compact(messages)
            visual_log("上下文压缩", "压缩完成",
                       f"压缩后消息条数：{len(messages)}", color="green")
        # s08: drain background notifications
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            messages.append({"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"})
            visual_log("注入消息", "已把后台任务结果注入给模型",
                       txt, color="yellow")
        # s10: check lead inbox
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"})
            visual_log("注入消息", "已把 lead 收件箱消息注入给模型",
                       inbox, color="magenta")
        system = build_system(messages)
        # LLM call
        visual_log("模型调用", "正在请求模型思考下一步",
                   {
                       "model": MODEL,
                       "messages": len(messages),
                       "tools": len(TOOLS),
                       "max_tokens": 8000,
                   }, color="cyan")
        response = client.messages.create(
            model=MODEL, system=system, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        visual_log("模型返回", f"stop_reason={response.stop_reason}",
                   content_blocks_summary(response.content), color="cyan")
        if response.stop_reason != "tool_use":
            visual_log("完成", "模型没有继续请求工具，本轮用户任务暂告一段落",
                       color="green")
            extract_memories(pre_compact + [{"role": "assistant", "content": response.content}])
            consolidate_memories()
            return
        # Tool execution
        results = []
        used_todo = False
        manual_compress = False
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "compress":
                    manual_compress = True
                handler = TOOL_HANDLERS.get(block.name)
                visual_log("工具调用", f"准备执行 {tool_label(block.name)}",
                           block.input, color="yellow")
                started = time.time()
                try:
                    allowed, reason = check_permission(block.name, block.input)
                    if not allowed:
                        output = f"Permission denied: {reason}"
                    else:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                elapsed = time.time() - started
                result_color = "red" if str(output).lower().startswith("error") else "green"
                visual_log("工具结果", f"{tool_label(block.name)} 执行完成，用时 {elapsed:.2f}s",
                           output, color=result_color)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                if block.name == "TodoWrite":
                    used_todo = True
        # s03: nag reminder (only when todo workflow is active)
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if TODO.has_open_items() and rounds_without_todo >= 3:
            visual_log("Todo提醒", "检测到仍有未完成 Todo，提醒模型更新清单",
                       TODO.render(), color="yellow")
            results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
        messages.append({"role": "user", "content": results})
        visual_log("工具回传", "已把工具执行结果追加到对话，模型将继续阅读结果",
                   f"tool_result 数量：{len(results)}", color="blue")
        # s06: manual compress
        if manual_compress:
            visual_log("上下文压缩", "模型请求手动压缩，开始 compact",
                       color="yellow")
            messages[:] = auto_compact(messages)
            visual_log("上下文压缩", "手动压缩完成，返回 REPL",
                       color="green")
            return


# === SECTION: repl ===
if __name__ == "__main__":
    visual_banner()
    history = []
    while True:
        try:
            query = input("\033[36ms_full >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        command = query.strip().lower()
        if command in ("q", "exit", ""):
            visual_log("退出", "收到退出命令，结束 REPL", color="yellow")
            break
        if command == "/visual off":
            VISUAL = False
            print("中文可视化追踪已关闭。输入 /visual on 可重新开启。")
            continue
        if command == "/visual on":
            VISUAL = True
            visual_banner()
            continue
        if query.strip() == "/compact":
            if history:
                visual_log("本地命令", "执行 /compact：手动压缩当前对话历史",
                           color="yellow", force=True)
                history[:] = auto_compact(history)
                visual_log("本地命令", "压缩完成",
                           f"当前消息条数：{len(history)}", color="green",
                           force=True)
            else:
                print("当前没有历史消息可压缩。")
            continue
        if query.strip() == "/tasks":
            visual_log("本地命令", "执行 /tasks：查看持久任务列表",
                       color="blue")
            print(TASK_MGR.list_all())
            continue
        if query.strip() == "/team":
            visual_log("本地命令", "执行 /team：查看队友状态",
                       color="magenta")
            print(TEAM.list_all())
            continue
        if query.strip() == "/inbox":
            visual_log("本地命令", "执行 /inbox：读取并清空 lead 收件箱",
                       color="magenta")
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            continue
        visual_log("用户输入", "收到新任务，加入对话历史",
                   query, color="cyan")
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            printed = False
            for block in response_content:
                if hasattr(block, "text"):
                    if not printed:
                        print(f"{_c('green')}[最终回答]{_c('reset')}")
                        printed = True
                    print(block.text)
        print()
