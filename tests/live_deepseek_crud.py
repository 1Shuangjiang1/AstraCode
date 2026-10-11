"""Manual real-API CRUD smoke test in an isolated system-temp workspace."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from agent_harness.app import AgentApp
from agent_harness.settings import Settings


BASE = Path(os.getenv("S_FULL_TEST_BASE") or tempfile.gettempdir()).resolve()


def main() -> int:
    if not BASE.is_dir():
        raise RuntimeError(f"Test base does not exist: {BASE}")
    root = Path(tempfile.mkdtemp(prefix="s_full_live_crud_", dir=BASE)).resolve()
    if not root.is_relative_to(BASE):
        raise RuntimeError(f"Unsafe test directory: {root}")

    report: dict = {"root": str(root), "steps": [], "cleaned": False}
    try:
        settings = replace(
            Settings.from_env(root),
            workdir=root,
            permission_mode="full_access",
            allow_critical=False,
            fake_client=False,
            visual=False,
            thinking_enabled=True,
            reasoning_effort="high",
            max_rounds=8,
            max_seconds=600,
            state_root=root / ".runtime",
        )
        if not (settings.api_key or settings.auth_token):
            raise RuntimeError("DeepSeek API credential is not configured")

        traces: list[dict] = []
        app = AgentApp(settings, trace_callback=traces.append)
        messages: list[dict] = []
        tasks = [
            (
                "create",
                "在当前工作目录创建 python_code_tutorial.md。写一份简洁的中文 Python 代码教程，"
                "必须包含变量、函数、类、异常处理和文件读写，并包含可运行代码示例。"
                "正文控制在 1200 个汉字以内。请直接使用 write_file 创建，然后用 read_file 验证。",
            ),
            (
                "edit",
                "修改 python_code_tutorial.md：把一级标题改为《Python 实战入门教程》，"
                "并在文末增加一个“练习：为加法函数编写 pytest 测试”的小节。"
                "请使用 edit_file 或 write_file 完成，并读取文件确认修改结果。",
            ),
            (
                "delete",
                "删除 python_code_tutorial.md，并使用 path_exists 确认它已经不存在。",
            ),
        ]

        for name, prompt in tasks:
            messages.append({"role": "user", "content": prompt})
            started = time.monotonic()
            status = app.agent_loop(messages, finalize_memory=False)
            path = root / "python_code_tutorial.md"
            if name == "create":
                assertion = path.is_file() and "函数" in path.read_text(encoding="utf-8")
            elif name == "edit":
                text = path.read_text(encoding="utf-8") if path.is_file() else ""
                assertion = "Python 实战入门教程" in text and "pytest" in text
            else:
                assertion = not path.exists()
            report["steps"].append({
                "name": name,
                "status": status,
                "assertion": assertion,
                "seconds": round(time.monotonic() - started, 2),
            })
            if status != "completed" or not assertion:
                raise RuntimeError(f"Live step failed: {name}, status={status}, assertion={assertion}")

        report["model_calls"] = sum(item.get("type") == "model_call_completed" for item in traces)
        report["model_failures"] = sum(item.get("type") == "model_call_failed" for item in traces)
        report["invalid_tool_results"] = sum(
            item.get("type") == "tool_evidence_recorded" and not item.get("ok") for item in traces
        )
        return_code = 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    finally:
        if root.is_relative_to(BASE) and root.name.startswith("s_full_live_crud_"):
            shutil.rmtree(root, ignore_errors=False)
            report["cleaned"] = not root.exists()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
