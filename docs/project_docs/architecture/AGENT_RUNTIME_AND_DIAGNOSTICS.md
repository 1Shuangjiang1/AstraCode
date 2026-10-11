# Agent 运行状态机与诊断日志方案

> 日期：2026-08-07  
> 状态：V1 已实现

## 1. 为什么纯文本不能直接等于任务完成

模型 API 的停止原因描述的是“这一轮生成为什么停下”，不是外部世界中的任务验收结果。

Anthropic 官方将 `end_turn` 定义为模型到达自然停止点；`tool_use` 表示等待客户端执行工具；`max_tokens` 表示输出被截断；`pause_turn` 需要继续当前处理；另外还有 `refusal`、`stop_sequence` 和上下文窗口耗尽等状态。DeepSeek 的 Anthropic 兼容接口复用这套消息格式。因此，宿主程序必须先解释协议状态，再判断业务任务是否完成。

参考：

- Anthropic Stop reasons：https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons
- DeepSeek Anthropic API：https://api-docs.deepseek.com/guides/anthropic_api/
- OpenAI Agents Runner：https://openai.github.io/openai-agents-python/ref/run/
- LangGraph Graph API：https://langchain-ai.github.io/langgraph/concepts/low_level/
- OpenTelemetry GenAI Agent spans：https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md

OpenAI Agents 的可借鉴点是：final output 可以有结构化类型，最终输出还可以经过 output guardrail；运行循环同时设置最大轮次并提供生命周期 hooks。LangGraph 的可借鉴点是：终止是状态图的显式条件边，而不是模型文本的隐含副作用。

## 2. s_full V1 四层判定

```text
DeepSeek 回包
  ↓
协议层：stop reason 是否允许进入完成候选？
  ↓
契约层：本轮属于聊天、检查、改动、命令还是委派？
  ↓
证据层：要求的工具类别是否至少成功一次？
  ↓
表达层：是否有非空、非“接下来要做”的最终结果？
  ↓
completed / continue / refused / incomplete
```

### 协议层

| stop reason | 处理 |
| --- | --- |
| `tool_use` | 执行工具并继续模型循环 |
| `end_turn` / DeepSeek `stop` | 仅进入完成候选 |
| `max_tokens` / `model_context_window_exceeded` | 追加继续指令，不算完成 |
| `pause_turn` | 恢复同一任务，不算完成 |
| `refusal` | 返回 `refused`，不伪装成功 |
| `stop_sequence` / 未知值 | 返回 `incomplete` |

### 契约与证据层

系统只对高置信度动作建立证据要求，普通聊天仍可直接回答：

- 文件改动：至少一次成功的 `write_file`、`edit_file` 或 `delete_file`；
- 命令/测试：至少一次成功的 `bash`、`background_run` 或 `check_background`；
- 项目检查：至少一次成功的读取、列目录、存在性检查、命令或 Explore 子 Agent；
- 明确委派：至少一次成功的 `task` 或 `spawn_teammate`。

一个请求可以同时需要多类证据。例如“运行测试并修复代码”必须同时具有改动证据和命令证据。

否定约束先于动作识别：“不要修改”“请勿写入”“without modifying”不会建立改动契约，并会在宿主层禁止 `write_file`、`edit_file` 和 `delete_file`。即使模型误发写入调用，也不会触达文件系统。

### 继续与熔断

未满足条件时会向模型注入内部 `<completion-guard>`，说明缺少的证据类别。最多继续 3 次，同时仍受全局最大轮次和最大运行时间限制。超过限制会明确变成 `incomplete`、`round_limit` 或 `time_limit`。

## 3. 诊断日志

原有会话总日志继续保留：

```text
%LOCALAPPDATA%\s_full\sessions\<session-id>\events.jsonl
```

新增每次运行独立日志：

```text
%LOCALAPPDATA%\s_full\sessions\<session-id>\runs\<request-id>.jsonl
```

执行记录的“会话已建立”条目会显示本次日志绝对路径。`task_completed`、`task_incomplete` 和 `error` 事件也携带同一路径。

每次运行记录：

- 用户请求与会话配置；
- 每轮模型请求时间、模型、消息数、工具数和上下文预算；
- response ID、真实 stop reason、内容块类型、文本长度和 token usage；
- 工具开始、结束、风险、结果预览和耗时；
- 自动压缩事件；
- 推断出的任务契约；
- 每次完成判定、缺少的证据、继续次数；
- 最终状态；
- 异常类型、错误信息和 Python traceback。

隐私边界：不记录 API Key，不新增完整思考内容采集；模型输出只记录类型、长度、usage 和最终可见回答。工具结果沿用 UI 的有限预览，避免诊断日志无界增长。用户请求和最终回答本来就是会话内容，会继续出现在本地日志中，因此分享日志前仍应检查其中是否含私人项目内容。

桌面端内部的 `.tasks`、`.team`、`.memory` 和 `.transcripts` 已迁移到当前 session 的应用数据目录，不再因为打开或只读检查项目而写入用户工作区。命令行兼容入口在未指定 `S_FULL_STATE_DIR` 时仍沿用原目录布局。

## 4. 执行记录折叠

执行记录标题现在是可访问按钮：

- 点击可展开或收起；
- 标题显示事件数量和 LIVE/COMPLETE/INCOMPLETE/CANCELLED；
- 折叠偏好保存在 localStorage，重启界面后保持；
- 动画使用 CSS grid，不依赖固定高度；
- `aria-expanded`、`aria-controls` 和键盘按钮行为完整；
- 系统启用“减少动态效果”时关闭折叠动画。

## 5. 后续演进

V1 仍是启发式任务契约。下一阶段建议：

1. 让 Plan 步骤显式声明 `acceptance_criteria` 和产物；
2. 写入后自动验证目标路径、内容摘要或 diff；
3. 将子 Agent/Teammate 的工具证据按 trace ID 汇总回主任务；
4. 增加日志查看器、按状态筛选和“一键复制诊断包”；
5. 支持可配置保留期、结果脱敏和日志大小上限；
6. 稳定后映射到 OpenTelemetry GenAI spans，当前 JSONL 字段保持可迁移。
