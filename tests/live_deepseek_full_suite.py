"""Real DeepSeek end-to-end acceptance suite for the complete agent harness.

The suite creates one isolated directory under the system temp root, exercises real model
calls and agent tools, writes a redacted JSON evidence file, then removes the
entire temporary workspace. It never records API keys or raw request headers.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_harness.app import AgentApp
from agent_harness.naming import generate_title
from agent_harness.permissions import PermissionEngine, Risk
from agent_harness.planning import PlanRunner, execution_prompt
from agent_harness.settings import Settings


BASE = Path(os.getenv("S_FULL_TEST_BASE") or tempfile.gettempdir()).resolve()
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "project_docs" / "testing" / "evidence"


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def tool_counts(traces: list[dict]) -> dict[str, int]:
    return dict(Counter(
        str(item.get("tool")) for item in traces
        if item.get("type") == "tool_evidence_recorded"
    ))


def tool_outcomes(traces: list[dict]) -> dict[str, dict[str, int]]:
    outcomes: dict[str, dict[str, int]] = {}
    for item in traces:
        if item.get("type") != "tool_evidence_recorded":
            continue
        bucket = outcomes.setdefault(str(item.get("tool")), {"passed": 0, "failed": 0})
        bucket["passed" if item.get("ok") else "failed"] += 1
    return outcomes


def completion_evaluations(traces: list[dict]) -> list[dict]:
    return [
        {
            "action": item.get("action"), "status": item.get("status"),
            "reason": item.get("reason"), "missing_evidence": item.get("missing_evidence") or [],
        }
        for item in traces if item.get("type") == "completion_evaluated"
    ]


def model_summary(traces: list[dict]) -> dict:
    completed = [item for item in traces if item.get("type") == "model_call_completed"]
    failed = [item for item in traces if item.get("type") == "model_call_failed"]
    return {
        "calls": len(completed),
        "failures": len(failed),
        "duration_ms": sum(int(item.get("duration_ms") or 0) for item in completed),
        "stop_reasons": dict(Counter(str(item.get("stop_reason")) for item in completed)),
    }


def make_app(root: Path, traces: list[dict], **overrides) -> AgentApp:
    settings = replace(
        Settings.from_env(PROJECT_ROOT),
        workdir=root,
        state_root=root / ".runtime",
        permission_mode="full_access",
        allow_critical=False,
        fake_client=False,
        visual=False,
        thinking_enabled=True,
        reasoning_effort="high",
        max_output_tokens=8192,
        max_rounds=14,
        max_seconds=600,
        command_timeout=45,
        poll_interval=1,
        idle_timeout=8,
        token_threshold=100000,
        **overrides,
    )
    if not (settings.api_key or settings.auth_token):
        raise RuntimeError("DeepSeek API credential is not configured")
    return AgentApp(settings, trace_callback=traces.append)


def run_agent_case(
    app: AgentApp,
    traces: list[dict],
    name: str,
    prompt: str,
    validate: Callable[[], tuple[bool, str]],
    required_tools: dict[str, int] | None = None,
) -> dict:
    start_index = len(traces)
    started = time.monotonic()
    messages = [{"role": "user", "content": prompt}]
    try:
        status = app.agent_loop(messages, finalize_memory=False)
        case_traces = traces[start_index:]
        counts = tool_counts(case_traces)
        outcomes = tool_outcomes(case_traces)
        valid, detail = validate()
        missing = {
            tool: expected - counts.get(tool, 0)
            for tool, expected in (required_tools or {}).items()
            if outcomes.get(tool, {}).get("passed", 0) < expected
        }
        passed = status == "completed" and valid and not missing
        return {
            "name": name,
            "status": "passed" if passed else "failed",
            "agent_status": status,
            "seconds": round(time.monotonic() - started, 2),
            "tools": counts,
            "tool_outcomes": outcomes,
            "missing_tools": missing,
            "assertion": detail,
            "model": model_summary(case_traces),
            "completion": completion_evaluations(case_traces),
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "failed",
            "seconds": round(time.monotonic() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "model": model_summary(traces[start_index:]),
            "completion": completion_evaluations(traces[start_index:]),
        }


def main() -> int:
    if not BASE.is_dir():
        raise RuntimeError(f"Test base does not exist: {BASE}")
    root = Path(tempfile.mkdtemp(prefix="s_full_live_full_", dir=BASE)).resolve()
    if not root.is_relative_to(BASE) or not root.name.startswith("s_full_live_full_"):
        raise RuntimeError(f"Unsafe test directory: {root}")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = EVIDENCE_DIR / f"full_suite_{datetime.now():%Y%m%d_%H%M%S}.json"
    report: dict = {
        "suite": "s_full real DeepSeek full acceptance",
        "started_at": now_text(),
        "model": None,
        "temporary_root": str(root),
        "cases": [],
        "cleaned": False,
    }
    traces: list[dict] = []
    app: AgentApp | None = None
    try:
        app = make_app(root, traces)
        report["model"] = app.settings.model

        report["cases"].append(run_agent_case(
            app, traces, "crud_todo_and_command",
            "这是严格的功能验收。先用 TodoWrite 建立三项清单：创建代码、运行验证、完成总结，"
            "任一时刻只能一项 in_progress。然后创建 calculator.py，包含 add 和 multiply 函数；"
            "再创建 test_calculator.py，使用 Python assert 验证两个函数。必须运行 "
            "python test_calculator.py，成功后把全部 Todo 更新为 completed。最后读取 calculator.py 并简短总结。",
            lambda: (
                (root / "calculator.py").is_file()
                and (root / "test_calculator.py").is_file()
                and not app.todo.has_open_items(),
                "calculator.py、test_calculator.py 存在，Todo 全部完成",
            ),
            {"TodoWrite": 2, "write_file": 2, "bash": 1, "read_file": 1},
        ))

        report["cases"].append(run_agent_case(
            app, traces, "persistent_tasks_and_skill",
            "这是工具验收，不要修改项目文件。必须依次完成：用 task_create 创建两个持久任务，"
            "主题分别为“检查计算模块”和“整理检查结论”；用 task_list 查看；用 task_update 将第一个任务标记 completed；"
            "用 task_get 读取第一个任务；最后用 load_skill 加载 code-review，并说明加载成功。",
            lambda: (
                len(app.tasks.list_data()) >= 2
                and any(item.get("status") == "completed" for item in app.tasks.list_data()),
                "至少两个持久任务，且存在 completed 任务",
            ),
            {"task_create": 2, "task_list": 1, "task_update": 1, "task_get": 1, "load_skill": 1},
        ))
        # Keep later teammate auto-claim behavior isolated from this tool case.
        for item in app.tasks.list_data():
            if item.get("status") != "completed":
                app.tasks.update(int(item["id"]), status="completed")

        (root / "legacy_parser.py").write_text(
            "def parse_int(value):\n    return int(value)\n", encoding="utf-8"
        )
        report["cases"].append(run_agent_case(
            app, traces, "single_explore_subagent",
            "必须且只能调用一次 task 工具，agent_type 使用 Explore，让子 agent 只读审查 legacy_parser.py 的"
            "输入边界和潜在异常。收到子 agent 结论后，由主 agent 创建 single_subagent_report.md，"
            "写入发现和两个改进建议，再读取该报告确认。不要让子 agent 修改文件。",
            lambda: (
                (root / "single_subagent_report.md").is_file()
                and "parse" in (root / "single_subagent_report.md").read_text(encoding="utf-8").lower(),
                "单子 Agent 报告存在并包含 parse 分析",
            ),
            {"task": 1, "write_file": 1, "read_file": 1},
        ))

        (root / "service.py").write_text(
            "def normalize(name):\n    return name.strip().lower()\n", encoding="utf-8"
        )
        (root / "test_service.py").write_text(
            "from service import normalize\nassert normalize(' Alice ') == 'alice'\n", encoding="utf-8"
        )
        report["cases"].append(run_agent_case(
            app, traces, "multiple_explore_subagents",
            "必须调用两次 task 工具并使用 Explore 子 agent：第一个只读审查 service.py 的实现，"
            "第二个只读审查 test_service.py 的测试覆盖。合并两份结论，由主 agent 写入 "
            "multi_subagent_report.md，明确分成“实现审查”和“测试审查”两节，再读取确认。",
            lambda: (
                (root / "multi_subagent_report.md").is_file()
                and all(token in (root / "multi_subagent_report.md").read_text(encoding="utf-8")
                        for token in ("实现审查", "测试审查")),
                "多子 Agent 报告包含两个独立审查章节",
            ),
            {"task": 2, "write_file": 1, "read_file": 1},
        ))

        report["cases"].append(run_agent_case(
            app, traces, "background_task",
            "必须使用 background_run 在后台执行这个 PowerShell 命令："
            "Start-Sleep -Seconds 2; Set-Content -LiteralPath 'background_result.txt' -Value 'BACKGROUND_OK' -Encoding UTF8。"
            "启动后必须使用 check_background 检查状态，若仍 running 就继续检查，直到 completed；"
            "然后读取 background_result.txt 验证内容。不要改用前台 bash 完成任务。",
            lambda: (
                (root / "background_result.txt").is_file()
                and "BACKGROUND_OK" in (root / "background_result.txt").read_text(encoding="utf-8"),
                "后台命令完成且结果文件内容正确",
            ),
            {"background_run": 1, "check_background": 1, "read_file": 1},
        ))

        report["cases"].append(run_agent_case(
            app, traces, "multiple_teammates",
            "这是 teammate 验收。必须使用 spawn_teammate 启动两个 teammate：alpha 角色为 writer，"
            "要求它创建 teammate_alpha.txt，内容包含 ALPHA_OK，然后 send_message 给 lead 并 idle；"
            "beta 角色为 writer，要求它创建 teammate_beta.txt，内容包含 BETA_OK，然后 send_message 给 lead 并 idle。"
            "主 agent 不得亲自写这两个文件。启动后用 list_teammates 查看状态，并反复使用 path_exists 检查两个文件；"
            "必要时用短暂的 Start-Sleep 等待。两个文件都出现后分别读取并总结。",
            lambda: (
                (root / "teammate_alpha.txt").is_file()
                and (root / "teammate_beta.txt").is_file()
                and "ALPHA_OK" in (root / "teammate_alpha.txt").read_text(encoding="utf-8")
                and "BETA_OK" in (root / "teammate_beta.txt").read_text(encoding="utf-8"),
                "两个真实 teammate 均创建了各自文件",
            ),
            {"spawn_teammate": 2, "list_teammates": 1, "path_exists": 2, "read_file": 2},
        ))
        for thread in list(app.team.threads.values()):
            thread.join(20)

        plan_started = time.monotonic()
        plan_trace_start = len(traces)
        plan_path = root / "plan_feature.py"
        try:
            plan_messages = [{"role": "user", "content": (
                "先制定只读计划：在当前项目新增 plan_feature.py，提供 slugify(text) 函数，"
                "并新增 test_plan_feature.py 用 assert 验证空格和大小写转换。计划阶段不要修改文件。"
            )}]
            plan, _markdown = PlanRunner(app).run(plan_messages, plan_messages[0]["content"])
            untouched = not plan_path.exists()
            execution_messages = [{"role": "user", "content": execution_prompt(plan)}]
            execution_status = app.agent_loop(execution_messages, finalize_memory=False)
            valid = (
                untouched and execution_status == "completed" and plan_path.is_file()
                and (root / "test_plan_feature.py").is_file()
            )
            report["cases"].append({
                "name": "plan_readonly_then_execute",
                "status": "passed" if valid else "failed",
                "agent_status": execution_status,
                "seconds": round(time.monotonic() - plan_started, 2),
                "plan": {"title": plan.get("title"), "steps": len(plan.get("steps") or []), "readonly": untouched},
                "tools": tool_counts(traces[plan_trace_start:]),
                "tool_outcomes": tool_outcomes(traces[plan_trace_start:]),
                "model": model_summary(traces[plan_trace_start:]),
                "completion": completion_evaluations(traces[plan_trace_start:]),
                "assertion": "Plan 阶段无写入，批准执行后代码和测试均存在",
            })
        except Exception as exc:
            report["cases"].append({
                "name": "plan_readonly_then_execute", "status": "failed",
                "seconds": round(time.monotonic() - plan_started, 2),
                "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(),
                "model": model_summary(traces[plan_trace_start:]),
            })

        chat_traces: list[dict] = []
        # AgentApp receives chat_mode separately; reuse the same isolated settings.
        chat_settings = replace(app.settings, state_root=root / ".chat-runtime")
        chat_app = AgentApp(chat_settings, chat_mode=True, trace_callback=chat_traces.append)
        report["cases"].append(run_agent_case(
            chat_app, chat_traces, "chat_mode_directory_selection",
            f"当前是聊天模式。必须先调用 set_working_directory 选择绝对目录 {root}，"
            "然后创建 chat_mode_result.txt，内容为 CHAT_MODE_OK，并读取确认。",
            lambda: (
                (root / "chat_mode_result.txt").is_file()
                and "CHAT_MODE_OK" in (root / "chat_mode_result.txt").read_text(encoding="utf-8"),
                "聊天模式先选择目录，再成功写入文件",
            ),
            {"set_working_directory": 1, "write_file": 1, "read_file": 1},
        ))
        chat_app.client.close()

        permission_started = time.monotonic()
        approvals: list[dict] = []
        approval_engine = PermissionEngine(
            root, "approval", False,
            lambda tool, args, decision, actor: approvals.append({
                "tool": tool, "risk": decision.risk.name, "actor": actor,
            }) or "y",
        )
        safe_engine = PermissionEngine(root, "safe", False)
        full_engine = PermissionEngine(root, "full_access", False)
        approval_write = approval_engine.authorize("write_file", {"path": "inside.txt", "content": "x"})
        approval_outside = approval_engine.authorize("read_file", {"path": str(BASE / "outside.txt")})
        safe_write = safe_engine.authorize("write_file", {"path": "inside.txt", "content": "x"})
        critical = full_engine.authorize("bash", {"command": "shutdown /s /t 0"})
        permissions_ok = (
            approval_write.allowed and not approval_write.needs_approval
            and approval_outside.allowed and approval_outside.needs_approval
            and not safe_write.allowed and critical.risk == Risk.CRITICAL and not critical.allowed
        )
        report["cases"].append({
            "name": "permission_boundaries",
            "status": "passed" if permissions_ok else "failed",
            "seconds": round(time.monotonic() - permission_started, 2),
            "assertion": "安全模式拒绝写入；审批模式仅高风险询问；完全访问仍拦截 critical",
            "approval_prompts": approvals,
        })

        naming_started = time.monotonic()
        try:
            title = generate_title(
                app.settings.title_api_key or "", app.settings.title_base_url,
                app.settings.title_model, "全面测试 Todo、子 Agent、Plan 和后台任务", timeout=45,
            )
            report["cases"].append({
                "name": "automatic_naming", "status": "passed" if bool(title) else "failed",
                "seconds": round(time.monotonic() - naming_started, 2),
                "provider_model": app.settings.title_model, "title": title,
            })
        except Exception as exc:
            report["cases"].append({
                "name": "automatic_naming", "status": "failed",
                "seconds": round(time.monotonic() - naming_started, 2),
                "error": f"{type(exc).__name__}: {exc}",
            })

        report["trace_totals"] = {
            "tools": tool_counts(traces),
            "model": model_summary(traces),
            "protocol_repairs": sum(item.get("type") == "message_protocol_repaired" for item in traces),
            "tool_failures": sum(
                item.get("type") == "tool_evidence_recorded" and not item.get("ok") for item in traces
            ),
        }
    except Exception as exc:
        report["suite_error"] = f"{type(exc).__name__}: {exc}"
        report["suite_traceback"] = traceback.format_exc()
    finally:
        if app is not None:
            for name in app.team.member_names():
                app.handle_shutdown_request(name)
            for thread in list(app.team.threads.values()):
                thread.join(5)
            app.client.close()
        if root.is_relative_to(BASE) and root.name.startswith("s_full_live_full_"):
            shutil.rmtree(root, ignore_errors=False)
            report["cleaned"] = not root.exists()
        report["finished_at"] = now_text()
        passed = sum(item.get("status") == "passed" for item in report["cases"])
        failed = sum(item.get("status") == "failed" for item in report["cases"])
        report["summary"] = {"passed": passed, "failed": failed, "total": len(report["cases"])}
        evidence_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "summary": report["summary"], "evidence": str(evidence_path),
            "cleaned": report["cleaned"],
            "failed_cases": [item["name"] for item in report["cases"] if item.get("status") == "failed"],
        }, ensure_ascii=False, indent=2))
    return 0 if report.get("summary", {}).get("failed") == 0 and "suite_error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
