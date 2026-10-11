# s_full 上下文模块开发档案

> 状态：第一阶段已实现  
> 最后更新：2026-08-06  
> 对应版本：0.4.0

## 1. 目标

这个模块解决的不是“把历史删得越多越好”，而是在以下三件事之间取平衡：

1. 模型继续知道用户目标、约束、当前进度、文件变更、错误和下一步；
2. 不反复发送已经过时的大段文件内容、目录列表和命令输出；
3. 被缩短的原始内容仍可恢复，方便调试、审计和后续重新读取。

本项目采用“双层记录”思路：SQLite 和事件日志保存完整会话；`ContextManager` 只负责生成每轮发给模型的临时视图。显示层的聊天记录、持久层的原始记录、模型实际收到的上下文不再被视为同一个东西。

## 2. 修改前：每次请求实际发送什么

Agent 模式下，每一轮 DeepSeek 请求包含：

- `system`：运行模式、Windows/PowerShell 约束、权限模式、工具使用提示、Skill 列表、Memory 索引和相关记忆；
- `messages`：本会话保存的全部用户消息、模型回复、工具调用和工具结果；
- `tools`：`schemas.py` 中当前注册的全部工具定义；
- `max_tokens=8000`；
- 客户端统一注入的思考开关与思考强度。

一次工具调用完成后，会追加两段历史：模型的 `tool_use`，以及用户角色承载的 `tool_result`。下一轮会将它们再次发给模型。最终回答也会追加进历史；下一次用户在同一对话继续提问时，Sidecar 会从 SQLite 的 `model_state` 恢复这份历史，再追加新问题。

Plan 模式同样恢复当前对话的模型历史，但使用只读规划系统提示，不提供执行工具。

修改前有两种瘦身机制：

- `microcompact`：保留最后 3 个工具结果，其余超过 100 字的结果直接变为 `[cleared]`；
- `auto_compact`：仅用 `len(JSON) / 4` 估算消息 token，超过默认 100000 后，将旧消息交给模型总结，保留最近约 12 条消息。

主要问题：`[cleared]` 丢失工具身份和结果含义；预算漏算系统提示、工具 schema 和输出预留；摘要触发之前缺乏可恢复的渐进压缩。

## 3. 外部项目调研

以下只采用产品官方文档或项目官方文档，不把无法验证的闭源内部实现当作事实。

### GitHub Copilot CLI

Copilot 明确把系统提示、用户消息、模型回复、工具调用和工具结果都算入上下文。超过 20 KiB 的工具输出会保存到临时文件，模型只收到路径和预览；上下文约 80% 时启动后台压缩，约 95% 时等待压缩完成。压缩摘要保留目标、完成事项、技术细节、文件和下一步，并保留原始用户指令及计划/Todo。这是本项目“原文落盘 + 结构化预览”和“预算必须包含工具”的主要参考。  
来源：[GitHub Copilot CLI context management](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/context-management)、[Copilot SDK session persistence](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/session-persistence)

### OpenAI Responses API

OpenAI 的公开 Compaction 机制以渲染后的 token 数量触发，把后续运行所需状态压成 compaction item；在无状态数组续接模式中，最近一次 compaction item 之前的项目可以丢弃。它说明“压缩结果应当成为正式的连续性状态”，而不只是 UI 上的一段摘要。当前 s_full 仍使用 Anthropic 兼容接口，因此只借鉴架构，不直接接入该 API。  
来源：[OpenAI API — Compaction](https://developers.openai.com/api/docs/guides/compaction)

### OpenHands

OpenHands 的 Condenser 使用 append-only 事件历史与面向模型的 `View` 分离；常见 rolling window 保留头部事件和尾部近期事件，总结中间区域，并记录被遗忘事件 ID。这个设计支持审计，也避免真正删除事件历史。s_full 的 SQLite/Event 与模型视图分层采用了同样的原则。  
来源：[OpenHands — Condenser](https://docs.openhands.dev/sdk/arch/condenser)

### Aider

Aider 不把整个仓库塞进上下文，而是生成包含关键文件、类、函数和签名的 Repo Map，再用依赖图排名选择与当前对话最相关的部分，并受动态 token budget 控制。它对 s_full 下一阶段“项目结构索引”很有参考价值。  
来源：[Aider — Repository map](https://aider.chat/docs/repomap.html)

### Cline

Cline 的 Auto Compact 在接近窗口限制时生成综合摘要并替换旧历史，Todo 可跨压缩保留；`/newtask` 则把计划、已完成工作、相关文件和下一步交接到新任务。Cline 还让子 Agent 使用独立上下文，只把调查报告带回主 Agent，减少主窗口污染。  
来源：[Cline — Auto Compact](https://docs.cline.bot/features/auto-compact)、[Cline — Subagents](https://docs.cline.bot/features/subagents)、[Cline — Tasks](https://docs.cline.bot/core-workflows/task-management)

### Claude Code

Claude Code 的公开文档重点说明分层记忆：用户级、项目级以及按目录发现的 `CLAUDE.md`；子目录记忆在读取对应子树时才加入，而不是启动时全部加载。这支持“稳定规则常驻、局部信息按需加载”的方向。  
来源：[Anthropic — Manage Claude's memory](https://docs.anthropic.com/zh-CN/docs/claude-code/memory)

## 4. 已实现方案

核心文件：`agent_harness/context.py`

### 4.1 完整请求预算

`ContextManager.measure()` 目前计算：

```text
请求预算 = messages + system + tool schemas + 8000 输出预留
```

仍使用字符数除以 4 的跨供应商近似值，因此它适合安全阈值和趋势展示，不等同于账单 token。达到 `S_FULL_TOKEN_THRESHOLD` 后才进入模型摘要。

### 4.2 渐进式工具结果压缩

每轮请求前扫描 `tool_use_id`，将它和原始 `tool_use` 的工具名、参数重新关联。默认保留最近 4 个工具结果完整内容；更早且超过 1200 字符的结果会被替换为：

```xml
<tool-result-compacted
  tool="read_file"
  status="ok"
  chars="..."
  sha256="..."
  artifact="...">
input: {"path":"..."}
preview:
头部内容
… [middle omitted] …
尾部内容
</tool-result-compacted>
```

原始文本写入：

```text
<工作目录>/.transcripts/tool-results/
```

因此模型仍能判断发生了什么、是否报错、涉及哪个路径，并可在需要时根据记录重新读取；调试人员也能直接打开原文。

### 4.3 大窗口摘要

超过预算后继续沿用并改进现有 `auto_compact`：

- 压缩前先把完整消息写入 `.transcripts/transcript_*.jsonl`；
- 优先在用户自然语言消息边界切分；
- 保留最近约 12 条消息；
- 摘要提示明确要求目标与约束、决策、文件、命令与验证、工作目录、Todo、错误和下一步；
- 摘要作为 `<conversation-summary>` 注入保留历史；
- Sidecar 把摘要和上下文状态同步写回当前对话数据库。

### 4.4 可观察性

上下文报告包含：消息、系统提示、工具 schema、输出预留、总请求估算、压缩结果数量、节省量和原文 artifact 路径。Sidecar 已支持发送 `context_trimmed` 事件，摘要仍发送 `context_compacted` 事件。

## 5. 关键信息保留规则

当前优先级从高到低为：

1. 系统安全边界、当前权限和工作目录；
2. 最新用户目标、约束和验收条件；
3. 最近对话和最近工具结果；
4. 失败、验证结果、文件写入/编辑/删除结果；
5. Todo、持久化任务和队友通信；
6. 老旧且可恢复的长文件内容、目录列表和命令输出。

第一阶段不会改写用户自然语言消息，也不会静默删除 SQLite 中的原始会话。

## 6. 测试

新增 `tests/test_context.py`：

- 验证旧的大工具输出被结构化压缩；
- 验证工具名、参数和原文可恢复；
- 验证预算包含 system、tools 和输出预留；
- 全量 Python 测试共 34 项通过；
- TypeScript 检查与 Vite 生产构建通过。

## 7. 当前限制与下一阶段

补充说明（2026-08-07）：一次“读取文档后只回复将要编写、随后结束”的故障经原始事件审计确认与上下文裁剪无关。该轮只有 3 个近期工具结果，均未被压缩；根因是完成状态机直接信任 provider stop reason。修复已独立落在 `completion.py`，详见 [`COMPLETION_GUARD.md`](COMPLETION_GUARD.md)。

1. **估算器不是精确 tokenizer**：后续可针对 DeepSeek 官方 tokenizer 增加精确计数，并保留近似回退。
2. **工具 schema 仍全部发送**：下一阶段可按“文件核心 / 子 Agent / Team / 后台任务”动态装载工具族，但必须先做回归评测，避免模型在需要时看不到工具。
3. **尚无 Repo Map**：可借鉴 Aider，为大型项目生成受预算约束的符号图，只注入当前任务相关部分。
4. **摘要只有单一最新状态**：后续可增加可恢复的 compaction checkpoint 表，并在 UI 中查看或回滚。
5. **保留优先级尚未语义评分**：当前以“最近结果 + 长度”作为稳定规则；后续可对错误、测试、写操作和重复输出分别打分。
6. **UI 还未显示详细预算**：目前 Inspector 只显示摘要 token；可新增上下文占用条及各组成部分。

## 8. 开发约束

- 不要重新引入不可恢复的 `[cleared]`；
- 不要把 UI 显示历史直接当作模型请求历史；
- 调整压缩阈值时必须同时考虑最大输出预留；
- 新工具必须评估其 schema 固定成本与输出体积；
- 修改摘要提示后，用“多轮改代码 + 测试失败 + 用户中途改要求”的案例做连续性回归；
- 任何动态工具筛选上线前，都要验证 Todo、子 Agent、Teammate 和审批流程仍可触发。
