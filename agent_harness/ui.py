from __future__ import annotations

import json
import threading
import time


COLORS = {
    "reset": "\033[0m", "dim": "\033[90m", "cyan": "\033[36m",
    "green": "\033[32m", "yellow": "\033[33m", "magenta": "\033[35m",
    "red": "\033[31m", "blue": "\033[34m",
}

TOOL_LABELS = {
    "set_working_directory": "选择工作目录",
    "bash": "运行 shell 命令", "read_file": "读取文件", "write_file": "写入文件",
    "list_directory": "列出目录", "path_exists": "检查路径", "delete_file": "删除文件",
    "edit_file": "编辑文件", "TodoWrite": "更新 Todo 清单", "task": "启动子 agent",
    "load_skill": "加载 skill", "compress": "压缩上下文", "background_run": "启动后台任务",
    "check_background": "检查后台任务", "task_create": "创建持久任务",
    "task_get": "读取任务详情", "task_update": "更新任务", "task_list": "列出任务",
    "spawn_teammate": "启动队友 agent", "list_teammates": "列出队友",
    "send_message": "发送队友消息", "read_inbox": "读取收件箱", "broadcast": "广播消息",
    "shutdown_request": "请求队友关闭", "plan_approval": "审批队友计划",
    "idle": "进入空闲状态", "claim_task": "认领任务",
}


class Console:
    def __init__(self, enabled: bool = True, preview_limit: int = 1200):
        self.enabled = enabled
        self.preview_limit = preview_limit
        self._lock = threading.RLock()

    def color(self, name: str) -> str:
        return COLORS.get(name, "") if self.enabled else ""

    def preview(self, value) -> str:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str, indent=2)
        value = value.strip()
        if len(value) <= self.preview_limit:
            return value
        return value[:self.preview_limit] + f"\n...（还有 {len(value) - self.preview_limit} 个字符未显示）"

    def log(self, stage: str, message: str = "", detail=None, color: str = "cyan", force: bool = False):
        if not self.enabled and not force:
            return
        title = f"{self.color(color)}[{time.strftime('%H:%M:%S')}] {stage:<14}{self.color('reset')}"
        if message:
            title += f" {message}"
        with self._lock:
            print(title)
            if detail is not None:
                for line in self.preview(detail).splitlines() or [""]:
                    print(f"{self.color('dim')}    {line}{self.color('reset')}")

    def banner(self, model: str, workdir, permission_mode: str, fake: bool):
        if not self.enabled:
            return
        print(f"{self.color('cyan')}+{'-' * 70}+{self.color('reset')}")
        print("| s_full 模块化 Agent Harness")
        print(f"  模型: {model}{' [FAKE/OFFLINE]' if fake else ''}")
        print(f"  工作目录: {workdir}")
        print(f"  权限模式: {permission_mode}")
        print("  命令: /compact /tasks /team /inbox /permissions /visual on|off")


def tool_label(name: str) -> str:
    label = TOOL_LABELS.get(name)
    return f"{name}（{label}）" if label else name


def content_blocks_summary(content) -> str:
    text_count = sum(getattr(block, "type", None) == "text" for block in content or [])
    tools = [getattr(block, "name", "unknown") for block in content or []
             if getattr(block, "type", None) == "tool_use"]
    parts = ([f"text x{text_count}"] if text_count else []) + (["tools: " + ", ".join(tools)] if tools else [])
    return "; ".join(parts) or f"{len(content or [])} block(s)"


def text_content(content) -> str:
    """Extract final-answer text while ignoring thinking/tool blocks and null content."""
    if isinstance(content, str):
        return content
    texts = []
    for block in content or []:
        if isinstance(block, dict):
            block_type, value = block.get("type"), block.get("text")
        else:
            block_type, value = getattr(block, "type", None), getattr(block, "text", None)
        if block_type == "text" and value:
            texts.append(str(value))
    return "\n".join(texts).strip()
