# s_full Plan 模式 V1 开发文档

> 状态：V1 已完成  
> 版本：0.5.0  
> 日期：2026-08-07

## 1. 开发前审查结论

开发前的 Plan 模式只是一个入口，不是完整规划工作流：

- 在线模式只进行一次不带工具的模型请求，无法读取真实项目；
- `plan_created` 中展示的四个步骤是 Sidecar 写死的，不是模型生成的结构化计划；
- 没有批准、要求修改和取消协议；
- 计划生成后直接以 `task_completed` 结束，不能批准后继续执行；
- 计划没有独立数据库记录，应用重启后无法可靠恢复待审批状态；
- UI 只能在右侧栏显示步骤标题，不能审阅依据、文件、验证和风险。

因此本次不是修补，而是实现第一版真实 Plan 状态机。

## 2. V1 目标与边界

V1 完成以下闭环：

```text
NORMAL
  ↓ 用户选择 Plan 并发送目标
PLANNING（只读探索）
  ↓ 生成结构化计划
WAITING_FOR_REVIEW
  ├─ revise → REVISING → PLANNING
  ├─ cancel → CANCELLED
  └─ approve → EXECUTING → VERIFYING → COMPLETED / FAILED
```

V1 的核心保证：

1. 规划阶段不能写文件，也不能运行命令；
2. 计划必须建立在实际读取的项目上下文之上；
3. 未经用户批准，不能进入 Agent 执行流程；
4. 用户可以要求修改并产生新的 revision；
5. 计划及状态存入 SQLite，可在应用重启后恢复；
6. 批准后把结构化计划作为执行契约交给现有 AgentApp。

## 3. 代码结构

### `agent_harness/planning.py`

Plan V1 的核心模块，包含：

- `PLAN_SYSTEM`：规划阶段系统提示；
- `READ_ONLY_PLAN_TOOLS`：只读工具白名单；
- `PlanRunner`：支持多轮工具调用的只读规划循环；
- `normalize_plan`：把模型结果转换为稳定结构；
- `plan_markdown`：生成面向用户的 Markdown 计划；
- `execution_prompt`：把获批计划转换为执行阶段契约。

只读探索默认最多 12 次工具调用。达到预算后，下一轮移除全部工具并要求模型立即输出最终 JSON，避免模型持续浏览项目而不收口。

### `agent_harness/sidecar.py`

负责状态机和桌面协议：

- 在线、离线计划生成；
- `plan_response` 审阅命令；
- 计划状态事件；
- 批准后启动 AgentApp；
- 执行完成、取消和失败的状态收口。

### `agent_harness/session_store.py`

数据库 schema 升级为 V2，增加 `plans` 表，用于保存：

- 计划 ID 和会话 ID；
- revision；
- 当前状态；
- 原始目标；
- 完整结构化计划；
- 项目路径、权限、模型、思考强度和离线标记；
- 创建和更新时间。

### 桌面端

- `desktop/src/types.ts`：PlanState、PlanStep、PlanRecord；
- `desktop/src/App.tsx`：事件恢复、计划审阅操作和主对话区计划卡；
- `desktop/src/styles.css`：计划卡、状态标签、步骤、风险和审阅按钮样式；
- `desktop/src/transport.ts`：浏览器 Demo 中的批准、修改、取消状态模拟。

## 4. 规划阶段安全边界

模型在 Plan 阶段只能看到四个工具：

```text
set_working_directory
read_file
list_directory
path_exists
```

以下能力不会出现在规划请求的 ToolList：

- `bash`
- `write_file`
- `edit_file`
- `delete_file`
- `background_run`
- 子 Agent 和 Teammate
- 持久化任务写操作

这是能力层隔离，不依赖模型“自觉不写”。即使当前权限选择了完全访问，规划模型也拿不到写入工具。

纯聊天模式下，如果需要文件上下文，模型必须先调用 `set_working_directory`，目录选择仍经过现有权限系统。

## 5. 结构化计划格式

```json
{
  "id": "plan-...",
  "revision": 1,
  "state": "waiting_for_review",
  "title": "计划标题",
  "summary": "修改目标和原因",
  "request": "原始用户目标",
  "assumptions": ["假设"],
  "steps": [
    {
      "id": "step-1",
      "title": "步骤标题",
      "description": "具体动作",
      "files": ["预计涉及的文件或区域"],
      "verification": "该步骤的验证方式",
      "status": "pending"
    }
  ],
  "risks": ["风险"],
  "verification": ["总体验证策略"]
}
```

模型输出无法解析时，`normalize_plan` 会生成最小两步计划，避免 UI 或状态机因格式问题崩溃；这只是容错，不代表模型输出质量合格。

## 6. 桌面协议

### 生成计划

沿用 `start_task`：

```json
{
  "command": "start_task",
  "mode": "plan",
  "prompt": "用户目标"
}
```

### 审阅计划

```json
{
  "command": "plan_response",
  "plan_id": "plan-...",
  "choice": "approve | revise | cancel",
  "feedback": "revise 时必填"
}
```

### 关键事件

- `plan_created`：完整结构化计划；
- `plan_state_changed`：状态、revision，以及完成时的步骤状态；
- `tool_started` / `tool_completed`：规划阶段的只读探索也会进入执行记录，并带 `planning=true`；
- `task_completed`：一次规划生成或一次批准执行结束。

Sidecar 的 `hello` 能力增加 `plan_review=true`。

## 7. 用户交互

计划生成后，主对话区显示独立审阅卡：

- 标题、revision 和状态；
- 摘要；
- 每个步骤的说明、预计文件和验证方式；
- 风险；
- 修改意见输入框；
- “取消计划”“要求修改”“批准并执行”三个操作。

“要求修改”会保留原始目标和已有模型历史，将用户意见作为新一轮上下文，生成 revision + 1。

“批准并执行”会把获批 JSON 作为明确执行契约交给 AgentApp。执行阶段恢复原权限策略，所有写入、命令、子 Agent 和 Teammate 仍经过原有权限系统与工作区锁。

## 8. 测试

新增和扩展的测试覆盖：

1. PlanRunner 只暴露四个只读工具；
2. 模型先读取文件、再返回结构化计划；
3. JSON 计划被正确标准化；
4. 离线计划可以批准，并经过 executing、verifying、completed；
5. 修改意见产生 revision 2，且保留原始目标；
6. 计划状态可以从 SQLite 读取；
7. 原有权限、上下文、会话、Sidecar 和文件工具测试不回归。

另完成一次真实 DeepSeek 在线只读冒烟测试：模型在只读工具预算内检查项目，返回标题为“为桌面端启动失败增加友好错误提示”的 4 步结构化计划，状态为 `waiting_for_review`；未执行批准，也未修改文件。

## 9. V1 已知限制

1. **步骤进度是阶段级的**：执行完成时统一把步骤标记为完成，尚未把 Agent 每次工具调用精确映射到具体 plan step。
2. **尚无自动 REPLANNING**：执行中发现事实变化时，Agent 会被要求报告偏离，但 V1 不会自动暂停并生成 revision。
3. **Plan 阶段不使用子 Agent**：这是为了第一版安全边界清晰；未来可增加只读 Explore 子 Agent。
4. **没有逐文件 Diff 审批**：批准的是整份计划，实际高风险操作仍由权限系统逐次审批。
5. **模型 JSON 使用提示约束和解析容错**：当前 DeepSeek Anthropic 兼容接口未在这里依赖供应商专属结构化输出参数。
6. **离线批准只验证状态机**：不会真的改文件，真实执行需要在线桌面模式。

## 10. 下一版本建议

建议 Plan V2 按此顺序开发：

1. 将 Todo/工具调用绑定到 plan step，实时显示步骤进度；
2. 执行偏离或验证失败时自动进入 `REPLANNING`，等待二次批准；
3. 加入只读 Explore 子 Agent，并限制返回体积；
4. 计划中显示预计文件 Diff 范围；
5. 增加“仅批准部分步骤”和“跳过步骤”；
6. 为真实 DeepSeek 在线规划增加固定评测集。
