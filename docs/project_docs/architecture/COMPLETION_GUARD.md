# Agent 完成判定修复档案

> 日期：2026-08-07  
> 状态：第一版已实现；2026-08-07 已扩展为通用运行状态机  
> 最新设计：见 [`AGENT_RUNTIME_AND_DIAGNOSTICS.md`](AGENT_RUNTIME_AND_DIAGNOSTICS.md)

## 1. 故障现象

用户要求在 `<TEST_ROOT>\算法教学` 创建《算法题目思路》Markdown 文档。Agent 依次选择目录、列出文件并读取已有题解，随后只回复“现在我来编写这份文档”，桌面端却立即显示 `COMPLETE`。目标文件实际上没有创建。

原始事件保存在：

`%LOCALAPPDATA%\s_full\sessions\15fc292d-401b-45ef-862b-665c1e8b0db9\events.jsonl`

事件证据：

- 会话运行在 `agent` 模式，而非本轮新增的 Plan 模式；
- 只有 `set_working_directory`、`list_directory`、`read_file` 三个只读操作；
- 没有 `write_file`、`edit_file` 或 `delete_file`；
- assistant 最终文本是未来动作说明，下一条事件却是 `task_completed`；
- 目录中不存在 `算法题目思路.md`。

## 2. 根因

根因在 `AgentApp.agent_loop` 的完成状态机，不在上下文压缩。

旧逻辑把 provider 的 `stop_reason != "tool_use"` 直接映射为 `completed`。但 `stop_reason` 只表示模型本次停止生成工具调用，不能证明用户要求的实际改动已经发生。因此，模型在读取资料后返回一段进度说明，也会被宿主误判为任务完成。

本次上下文没有被裁剪：`ContextPolicy.keep_recent_tool_results` 默认为 4，而失败轮次只有 3 个工具结果；总请求也远低于 100,000 token 自动摘要阈值。读取到的旧文档仍完整位于发给模型的临时上下文中。

## 3. 第一版完成门槛

新增 `agent_harness/completion.py`：

1. 从本轮最新自然语言用户消息中保守识别中英文文件改动请求；
2. 只记录本轮成功完成的 `write_file`、`edit_file`、`delete_file`；
3. 如果文件改动请求尚无成功写操作，而模型返回普通文本，则插入不可见于聊天展示的 `<completion-guard>` 纠正消息并继续运行；
4. 最多纠正两次，防止模型异常造成无限循环；
5. 两次纠正后仍未执行改动，返回 `incomplete`，不再伪装成成功。

系统提示同时增加语义约束：进度公告不是完成结果；文件改动任务必须在改动工具成功后才能结束。

## 4. 桌面状态

Sidecar 新增 `task_incomplete` 终止事件。桌面端收到后会：

- 停止运行态；
- 将会话状态设为错误/未完成；
- 执行记录显示 `INCOMPLETE`；
- 右侧概览显示“未完成”；
- 展示可重试提示，而不是绿色 `COMPLETE`。

SQLite 会把 `task_incomplete` 持久化为会话错误状态，重启后不会恢复成已完成。

## 5. 测试结果

离线回归覆盖：

- 中文“写一个全新的 md 文档”可被识别；
- 读取后只说“现在我来编写”会被强制继续；
- 后续实际写入并回答时正常完成；
- 连续三次只说不做时返回 `incomplete`；
- 纯解释型问答无需文件操作即可正常结束。

全量 Python：42 项通过。React/TypeScript 生产构建通过。

真实 DeepSeek 在线测试在项目外的 `<TEST_ROOT>\s_full_completion_guard_smoke` 进行：High 思考模式在约 51 秒内读取示例文档并创建 13,884 字节的 `算法题目思路.md`，状态为 `completed`。测试目录随后已完整清理。

## 6. 当前边界与后续建议

第一版门槛刻意只处理高置信度文件改动，避免把普通咨询强制变成工具任务。它尚未证明“文件内容完全符合需求”，也没有把 shell 内的任意副作用当作可靠写入证据。

后续通用版本已在 `completion.py` 中增加命令、检查和委派证据，并显式区分 `max_tokens`、`pause_turn`、`refusal` 等停止原因；本文件保留作为原始故障档案。

后续可继续加入：

- 按任务类型声明产物与验收条件，而不是只依赖关键词；
- 对目标路径做 `path_exists` 或内容级验收；
- 将子 Agent/Teammate 的实际变更汇总进同一完成证据；
- 把测试、构建和用户指定验收命令纳入 `VerificationPolicy`；
- 将纠正次数、原因和完成证据显示在开发者诊断面板。
