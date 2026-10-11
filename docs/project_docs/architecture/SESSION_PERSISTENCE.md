# 会话与项目持久化方案

> 状态：0.3.0 已实现 SQLite 会话库、追加式事件日志、模型上下文恢复、自动压缩摘要、置顶、归档与删除。文件检查点仍是后续工程任务。

## 1. 这次调研得到的共性

主流编程 Agent 并不只保存“用户和模型说了什么”，而是把一次工作看作可恢复的执行会话：

- Claude Code 用会话 ID 恢复，并支持继续当前目录最近一次会话，说明会话身份与工作目录需要稳定关联。
- Cursor 将聊天历史保存在本地数据库，提供重命名、删除、Markdown 导出和引用历史聊天；另外用检查点保存 Agent 造成的文件变化。
- GitHub Copilot SDK 的持久化范围包含完整对话、工具结果、计划和产物；Copilot CLI 还保存工具调用和修改过的文件，并用本地结构化索引支持查找与恢复。
- Codex/ChatGPT 的产品结构区分聊天和项目；项目用于聚合聊天、文件和指令，编码工作还需要项目、差异和进度上下文。

参考资料：

- [Claude Code CLI：继续和恢复会话](https://docs.anthropic.com/en/docs/claude-code/cli-usage)
- [Cursor：聊天历史](https://docs.cursor.com/en/agent/chat/history)
- [Cursor：检查点](https://docs.cursor.com/en/agent/chat/checkpoints)
- [GitHub Copilot SDK：会话持久化](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/session-persistence)
- [GitHub Copilot CLI：会话数据](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/copilot-cli/chronicle)
- [GitHub Copilot CLI：上下文压缩](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/context-management)
- [OpenAI：Chat、项目与 Codex 的工作方式](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)

## 2. s_full 推荐的信息结构

### 项目记录

每个项目保存：

- `project_id`：内部稳定 ID，不依赖目录名。
- `name`、规范化绝对路径、仓库标识（如果是 Git 仓库）。
- 创建时间、最后打开时间、默认权限、默认模型和项目级指令。
- 对话 ID 列表；删除项目记录时不自动删除真实项目文件。

### 单个对话

单个对话建议保存以下内容：

1. 身份与配置：会话 ID、标题、所属模式/项目、创建与更新时间、模型、思考强度、权限策略、版本号。
2. 完整消息：用户消息、助手消息、时间戳、附件引用；模型续聊所需的原始响应字段也应保留。
3. 执行事件：工具名、参数的安全摘要、结果、耗时、状态和错误；审批请求及用户选择。
4. 工作上下文：当前工作目录、允许访问的根目录、计划与 Todo、关键决策、下一步。
5. 文件影响：新增/修改/删除文件列表、前后哈希、可选 diff，以及 Agent 自动修改前的检查点。
6. 运行状态：运行中、完成、取消或失败；断电重启后不能把“运行中”误显示成仍在执行。
7. 压缩摘要：长对话压缩时保留目标、已经完成的动作、重要文件、当前计划和待办事项。

绝不保存 API Key、完整环境变量、密码或未经脱敏的敏感工具参数。设置中只保存“已配置”状态，密钥继续交给系统安全存储或本地受限配置。

## 3. 推荐的本地磁盘布局

```text
.s_full/
├── index.sqlite                  # 项目、会话元数据、排序和搜索索引
├── sessions/
│   └── <session-id>/
│       ├── events.jsonl          # 追加式消息、工具、审批和状态事件
│       ├── summary.json          # 目标、决策、计划、重要文件、下一步
│       ├── artifacts/            # 对话附件与生成产物的引用或副本
│       └── checkpoints/
│           └── manifest.json     # 检查点、文件哈希和补丁索引
└── settings.json                 # 非敏感全局设置；不含 API Key
```

采用 SQLite + JSONL 的原因：SQLite 适合快速列出、排序和搜索大量对话；JSONL 是追加式事件日志，Agent 意外退出时比反复覆盖一个大 JSON 更容易恢复。检查点应只记录 Agent 改动，不能替代 Git，也不应该覆盖用户在会话外的手工改动。

## 4. 单轮和多轮实际传给模型什么

一次用户请求进入 Agent 模式后，发送给 DeepSeek 的内容由三部分组成：

1. 每轮动态生成的 system prompt：工作目录、项目/聊天模式、权限、Windows PowerShell 约束、工具说明、技能和相关长期记忆。
2. 当前会话的 `messages`：从该会话第一轮开始的用户消息、模型完整响应块（包括 text、thinking 和 tool_use）以及与 tool-use ID 匹配的 tool_result。
3. 当前轮产生的后台任务结果、teammate inbox 等临时消息。

模型每调用一次工具，完整 `messages` 会增加“assistant tool_use + user tool_result”，随后再次整体发送。因此单个用户请求内部也可能发生多次模型轮次。下一次用户继续同一对话时，新问题追加到原历史后再次发送；切换到另一个对话则使用另一个 session ID 的独立历史。

Plan 模式现在也复用同一会话的模型历史，但使用只读 planning system prompt，不会把其他对话或同项目的其他会话混进来。

## 5. 上下文压缩和摘要

- 每次模型调用前先估算消息 token（当前采用 JSON 字符数 / 4 的保守近似）。
- 先清理较旧的大型工具输出，只保留最近三个完整 tool result。
- 默认估算超过约 100,000 token 时触发自动压缩；可以用 `S_FULL_TOKEN_THRESHOLD` 调整。
- 压缩模型必须保留目标、约束、决策、读写文件、命令与验证结果、活动目录、Todo、错误和下一步。
- 较旧轮次被摘要替换，同时保留最近约 12 条消息，并从安全的用户轮次边界切分，避免拆开 tool_use/tool_result。
- 压缩前的完整历史写入项目 `.transcripts/`；结构化摘要、压缩后模型历史、消息数和 token 估算写入 SQLite。
- UI 时间线显示“上下文已压缩”，右侧 Inspector 显示当前摘要。重启应用后从 SQLite 恢复压缩后的历史，不重新拼凑工具调用。

## 6. 当前 0.3.0 已实现

- 侧边栏顶部在项目模式和纯聊天模式间切换。
- 项目模式支持添加多个目录，每个项目独立显示自己的对话。
- 项目旁的 `+` 会直接在该项目下新建对话；纯聊天模式的 `+` 只创建无项目对话。
- Python sidecar 在 `%LOCALAPPDATA%/s_full/index.sqlite` 保存项目、会话、消息、执行事件和模型状态；可用 `S_FULL_DATA_DIR` 改位置。
- 每个会话同时追加 `%LOCALAPPDATA%/s_full/sessions/<session-id>/events.jsonl` 审计日志。
- 首次升级且数据库为空时，桌面端会把已有 localStorage 项目和会话导入数据库；localStorage 继续作为浏览器预览和启动兜底缓存。
- 同一对话的模型原始历史可跨应用重启恢复；旧 UI 会话没有完整工具块时，只能迁移可见的用户/助手文字。
- 项目对话与纯聊天都支持置顶、归档、恢复和永久删除。归档会隐藏但保留全部数据；删除需要确认并清除数据库行、模型状态和会话事件目录。

## 7. 数据库表

- `projects`：项目 ID、名称、路径和时间。
- `sessions`：工作空间、标题、模型和权限、活动目录、置顶/归档、摘要和上下文 token。
- `messages`：用于 UI 展示和导出的用户/助手文本。
- `events`：工具、审批、状态、错误和压缩事件的结构化审计记录。
- `model_state`：可以直接还原给 Anthropic 兼容 API 的完整 content blocks，以及最近的压缩摘要。
- `schema_meta`：数据库迁移版本。

## 8. 后续实施顺序

1. 增加会话重命名、搜索和导出 Markdown。
2. 永久删除之前增加可配置的回收站保留期。
3. 在写文件工具前生成轻量检查点，UI 增加“查看改动”和“恢复本次 Agent 改动”。
4. 用真实 provider usage 替换近似 token 统计，并增加多级压缩策略。
5. 完成崩溃恢复和 SQLite schema migration 测试，再考虑跨设备同步。
