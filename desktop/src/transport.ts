import type { AgentMode, PermissionMode, SidecarEvent } from "./types";

type EventHandler = (event: SidecarEvent) => void;
type LogHandler = (line: string) => void;
type Unlisten = () => void;

const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

function now() {
  return new Date().toISOString();
}

export class WorkbenchBridge {
  readonly desktop = isTauri();
  private onEvent: EventHandler = () => undefined;
  private onLog: LogHandler = () => undefined;
  private unlisten: Unlisten[] = [];
  private timers: number[] = [];
  private taskTimers: number[] = [];

  async connect(onEvent: EventHandler, onLog: LogHandler): Promise<string> {
    this.onEvent = onEvent;
    this.onLog = onLog;
    if (!this.desktop) {
      this.schedule(140, () =>
        this.emit({
          type: "ready",
          timestamp: now(),
          request_id: "browser-hello",
          protocol_version: 1,
          app_version: "0.8.1-demo",
          capabilities: { offline: true, real_agent: false, plan_review: true },
        }),
      );
      return "浏览器演示工作区（启动 Tauri 后可选择真实项目）";
    }

    const [{ invoke }, { listen }] = await Promise.all([
      import("@tauri-apps/api/core"),
      import("@tauri-apps/api/event"),
    ]);
    this.unlisten.push(
      await listen<string>("sidecar-event", ({ payload }) => {
        try {
          this.emit(JSON.parse(payload) as SidecarEvent);
        } catch {
          this.onLog(`sidecar 返回了无法解析的消息：${payload}`);
        }
      }),
      await listen<string>("sidecar-log", ({ payload }) => this.onLog(payload)),
      await listen("sidecar-exit", () =>
        this.emit({ type: "sidecar_exit", timestamp: now(), message: "Python sidecar 已退出" }),
      ),
    );
    await invoke("sidecar_start");
    const project = await invoke<string>("default_project_path");
    await this.send({ command: "hello", request_id: crypto.randomUUID() });
    return project;
  }

  async chooseProject(): Promise<string | null> {
    if (!this.desktop) return null;
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({ directory: true, multiple: false, title: "选择 agent 工作项目" });
    return typeof selected === "string" ? selected : null;
  }

  async revealLog(path: string): Promise<void> {
    if (!this.desktop) throw new Error("浏览器演示模式无法打开本地日志文件夹。");
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("reveal_log_file", { path });
  }

  async revealWorkspaceItem(root: string, relativePath?: string): Promise<void> {
    if (!this.desktop) throw new Error("浏览器演示模式无法打开本地文件夹。");
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("reveal_workspace_item", { root, relativePath: relativePath || null });
  }

  async send(payload: Record<string, unknown>): Promise<void> {
    if (this.desktop) {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("sidecar_send", { payload: JSON.stringify(payload) });
      return;
    }
    if (payload.command === "start_task") this.runDemo(payload);
    if (payload.command === "get_settings") this.schedule(40, () => this.emit({
      type: "settings_snapshot", timestamp: now(), request_id: String(payload.request_id),
      model: "deepseek-v4-flash", title_model: "deepseek-ai/DeepSeek-V4-Flash",
      title_base_url: "https://api.siliconflow.cn/v1", title_api_key_configured: true,
      base_url: "https://api.deepseek.com/anthropic", api_key_configured: true, command_timeout: 30,
    }));
    if (payload.command === "get_tools") this.schedule(40, () => this.emit({
      type: "tools_snapshot", timestamp: now(), request_id: String(payload.request_id),
      tools: [
        { name: "set_working_directory", description: "选择聊天模式的活动目录。" },
        { name: "bash", description: "运行非交互 PowerShell 命令。" },
        { name: "read_file", description: "读取文件内容。" },
        { name: "write_file", description: "写入文件内容。" },
      ],
    }));
    if (payload.command === "get_skills") this.schedule(42, () => this.emit({
      type: "skills_snapshot", timestamp: now(), request_id: String(payload.request_id),
      skills: [
        { name: "code-review", description: "系统化审查正确性、安全性与测试缺口。" },
        { name: "frontend-design", description: "设计并实现高质量前端界面。" },
        { name: "testing", description: "制定并执行与风险相称的测试策略。" },
      ],
    }));
    if (payload.command === "get_library") this.schedule(45, () => this.emit({
      type: "library_snapshot", timestamp: now(), request_id: String(payload.request_id),
      projects: [], conversations: [], dataPath: "browser-localStorage", schemaVersion: 1,
    }));
    if (payload.command === "get_recovery") this.schedule(45, () => this.emit({
      type: "recovery_snapshot", timestamp: now(), request_id: String(payload.request_id), runs: [],
    }));
    if (payload.command === "dismiss_recovery") this.schedule(30, () => this.emit({
      type: "recovery_dismissed", timestamp: now(), request_id: String(payload.request_id),
      target_request_id: String(payload.target_request_id), ok: true,
    }));
    if (payload.command === "undo_run") this.schedule(80, () => this.emit({
      type: "rollback_completed", timestamp: now(), request_id: String(payload.request_id),
      target_request_id: String(payload.target_request_id), ok: true, state: "rolled_back",
      change_set: { id: String(payload.target_request_id), state: "rolled_back", files: [], totals: { files: 0, additions: 0, deletions: 0 } },
    }));
    if (payload.command === "save_library") this.schedule(30, () => this.emit({
      type: "library_saved", timestamp: now(), request_id: String(payload.request_id),
    }));
    if (payload.command === "set_session_state") this.schedule(30, () => this.emit({
      type: "session_state_saved", timestamp: now(), request_id: String(payload.request_id),
      session_id: String(payload.session_id || ""), ok: true,
    }));
    if (payload.command === "delete_session") this.schedule(30, () => this.emit({
      type: "session_deleted", timestamp: now(), request_id: String(payload.request_id),
      session_id: String(payload.session_id || ""), ok: true,
    }));
    if (payload.command === "update_settings") this.schedule(80, () => this.emit({
      type: "settings_snapshot", timestamp: now(), request_id: String(payload.request_id), saved: true,
      model: payload.model, title_model: payload.title_model, title_base_url: payload.title_base_url,
      title_api_key_configured: true, base_url: payload.base_url, api_key_configured: true,
      command_timeout: payload.command_timeout,
    }));
    if (payload.command === "plan_response") {
      const base = { request_id: String(payload.request_id), session_id: String(payload.session_id), plan_id: String(payload.plan_id) };
      const choice = String(payload.choice);
      this.scheduleTask(60, () => this.emit({ type: "response", timestamp: now(), ...base, command: "plan_response", ok: true }));
      if (choice === "cancel") this.scheduleTask(100, () => this.emit({ type: "plan_state_changed", timestamp: now(), ...base, state: "cancelled" }));
      if (choice === "revise") {
        this.scheduleTask(100, () => this.emit({ type: "plan_state_changed", timestamp: now(), ...base, state: "revising" }));
        this.scheduleTask(420, () => this.emit({ type: "plan_created", timestamp: now(), ...base,
          id: String(payload.plan_id), revision: 2, state: "waiting_for_review", title: "修订后的离线计划",
          summary: `已根据意见调整：${String(payload.feedback || "")}`,
          assumptions: [], risks: ["浏览器模式只模拟计划状态机"], verification: ["在 Tauri 模式执行真实验证"],
          steps: [
            { id: "step-1", title: "重新确认范围", description: "应用用户的计划修改意见。", files: [], verification: "确认范围一致", status: "pending" },
            { id: "step-2", title: "实施与验证", description: "按修订计划执行。", files: [], verification: "运行相关测试", status: "pending" },
          ],
        }));
        this.scheduleTask(470, () => this.emit({ type: "task_completed", timestamp: now(), ...base, status: "planned", summary: "计划已修订" }));
      }
      if (choice === "approve") {
        this.scheduleTask(100, () => this.emit({ type: "plan_state_changed", timestamp: now(), ...base, state: "executing" }));
        this.scheduleTask(560, () => this.emit({ type: "plan_state_changed", timestamp: now(), ...base, state: "verifying" }));
        this.scheduleTask(760, () => this.emit({ type: "plan_state_changed", timestamp: now(), ...base, state: "completed" }));
        this.scheduleTask(800, () => this.emit({ type: "assistant_message", timestamp: now(), ...base, content: "离线演示已完成批准、执行和验证状态流。" }));
        this.scheduleTask(850, () => this.emit({ type: "task_completed", timestamp: now(), ...base, status: "completed", summary: "批准的计划已完成" }));
      }
    }
    if (payload.command === "cancel_task") {
      this.taskTimers.forEach((timer) => window.clearTimeout(timer));
      this.taskTimers = [];
      this.schedule(50, () => this.emit({
        type: "task_cancelled", timestamp: now(), message: "任务已由用户停止",
        request_id: String(payload.target_request_id || "demo-task"),
      }));
    }
  }

  async disconnect(): Promise<void> {
    this.timers.forEach((timer) => window.clearTimeout(timer));
    this.timers = [];
    this.taskTimers.forEach((timer) => window.clearTimeout(timer));
    this.taskTimers = [];
    this.unlisten.splice(0).forEach((stop) => stop());
    if (this.desktop) {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("sidecar_stop").catch(() => undefined);
    }
  }

  private emit(event: SidecarEvent) {
    this.onEvent(event);
  }

  private schedule(delay: number, callback: () => void) {
    this.timers.push(window.setTimeout(callback, delay));
  }

  private scheduleTask(delay: number, callback: () => void) {
    this.taskTimers.push(window.setTimeout(callback, delay));
  }

  private runDemo(payload: Record<string, unknown>) {
    const request_id = String(payload.request_id);
    const session_id = String(payload.session_id || `demo-${Date.now()}`);
    const mode = payload.mode as AgentMode;
    const permission = payload.permission as PermissionMode;
    const base = { request_id, session_id };
    this.taskTimers.forEach((timer) => window.clearTimeout(timer));
    this.taskTimers = [];
    this.scheduleTask(80, () => this.emit({ type: "response", timestamp: now(), ...base, ok: true }));
    this.scheduleTask(180, () =>
      this.emit({
        type: "session_started",
        timestamp: now(),
        ...base,
        mode,
        permission,
        offline: true,
        project_path: payload.project_path,
      }),
    );
    this.scheduleTask(380, () =>
      this.emit({ type: "status", timestamp: now(), ...base, phase: "understanding", message: "正在理解任务与边界" }),
    );
    this.scheduleTask(430, () => this.emit({ type: "todo_updated", timestamp: now(), ...base, items: [
      { content: "检查工作区", status: "completed", activeForm: "正在检查工作区" },
      { content: "实施任务", status: "in_progress", activeForm: "正在实施任务" },
      { content: "验证结果", status: "pending", activeForm: "正在验证结果" },
    ] }));
    this.scheduleTask(500, () => this.emit({ type: "agent_started", timestamp: now(), ...base, agent_id: "subagent:demo", agent_kind: "subagent", name: "Explore", role: "Explore", prompt: "检查相关实现并汇报证据", status: "started" }));
    this.scheduleTask(560, () => this.emit({ type: "agent_status", timestamp: now(), ...base, agent_id: "subagent:demo", agent_kind: "subagent", name: "Explore", status: "thinking", round: 1 }));
    this.scheduleTask(670, () =>
      this.emit({
        type: "tool_started",
        timestamp: now(),
        ...base,
        tool_id: "demo-inspect",
        tool: "inspect_workspace",
        label: "检查项目结构",
        risk: "low",
      }),
    );
    this.scheduleTask(1080, () =>
      this.emit({
        type: "tool_completed",
        timestamp: now(),
        ...base,
        tool_id: "demo-inspect",
        tool: "inspect_workspace",
        ok: true,
        result: "浏览器预览已完成模拟扫描；Tauri 模式会由 Python 读取真实项目。",
      }),
    );
    this.scheduleTask(1160, () => this.emit({ type: "agent_tool_completed", timestamp: now(), ...base, agent_id: "subagent:demo", agent_kind: "subagent", name: "Explore", tool: "list_directory", ok: true, result: "项目结构检查完成" }));
    this.scheduleTask(1210, () => this.emit({ type: "agent_completed", timestamp: now(), ...base, agent_id: "subagent:demo", agent_kind: "subagent", name: "Explore", status: "completed", summary: "已完成只读调研。" }));
    if (mode === "plan") {
      this.scheduleTask(1290, () =>
        this.emit({
          type: "plan_created",
          timestamp: now(),
          ...base,
          id: `demo-plan-${session_id}`,
          revision: 1,
          state: "waiting_for_review",
          title: "离线 Plan V1 执行计划",
          summary: "先确认范围，再实施变更，最后运行对应验证。",
          assumptions: [],
          risks: ["浏览器预览不会修改真实文件"],
          verification: ["在 Tauri 桌面模式运行真实测试"],
          steps: [
            { id: "step-1", title: "确认修改范围", description: "阅读相关实现与约束。", files: [], verification: "记录受影响区域", status: "pending" },
            { id: "step-2", title: "实施计划变更", description: String(payload.prompt), files: [], verification: "检查文件差异", status: "pending" },
            { id: "step-3", title: "验证并总结", description: "运行与变更匹配的测试。", files: [], verification: "测试通过", status: "pending" },
          ],
        }),
      );
    }
    this.scheduleTask(1540, () =>
      this.emit({
        type: "assistant_message",
        timestamp: now(),
        ...base,
        content:
          mode === "plan"
            ? `已为“${payload.prompt}”生成可审阅计划。请选择批准执行、要求修改或取消。`
            : `已收到“${payload.prompt}”。桌面事件链路正常；接入真实 AgentApp 后，这里会显示实际修改结果。`,
      }),
    );
    this.scheduleTask(1580, () => this.emit({
      type: "change_set_ready", timestamp: now(), ...base,
      change_set: { id: request_id, root: String(payload.project_path || "D:\\demo"), state: "ready", files: [{ path: "demo.md", status: "created", additions: 13, deletions: 0, diff: "--- /dev/null\n+++ demo.md\n@@ -0,0 +1,13 @@\n+# AstraCode 示例\n+\n+## 已生成内容\n+\n+- Markdown 预览\n+- Diff 检查\n+- 一键打开文件夹\n+\n+## 代码示例\n+\n+```python\n+print(\"Hello AstraCode\")\n+```", after_preview: "# AstraCode 示例\n\n## 已生成内容\n\n- Markdown 预览\n- Diff 检查\n- 一键打开文件夹\n\n## 代码示例\n\n```python\nprint(\"Hello AstraCode\")\n```" }], totals: { files: 1, additions: 13, deletions: 0 } },
    }));
    this.scheduleTask(1600, () => this.emit({
      type: "verification_completed", timestamp: now(), ...base, mode: payload.verification_mode || "standard",
      verdict: "pass", passed: true, summary: "演示验证已核对需求、文件变更和工具结果。", checks: [], issues: [], confidence: .94,
    }));
    this.scheduleTask(1660, () =>
      this.emit({
        type: "task_completed",
        timestamp: now(),
        ...base,
        status: mode === "plan" ? "planned" : "completed",
        summary: "离线桌面链路验证完成",
      }),
    );
  }
}
