# AstraCode 0.8.1 项目交接文档

> 用途：让第一次接触项目的开发者或 AI 快速了解“项目做什么、已经具备什么、代码和详细资料在哪里”。本文只记录项目事实和导航，不规定讲解方式。
>
> 当前基线：AstraCode 0.8.1；整理日期：2026-08-12。

## 1. 项目是什么

AstraCode 是一个本地桌面 Coding Agent。用户选择本地项目后，可以直接用自然语言要求 Agent 阅读代码、创建或修改文件、运行命令、制定计划、调用子 Agent、检查结果，并在界面中查看执行过程和文件变化。

项目起点是 `learn-claude-code` 的教学文件 `s_full.py`。原版已经包含 Agent 工具循环、Todo、持久任务板、Skill、上下文压缩、长期 Memory、后台任务、子 Agent、Teammate 和团队消息等机制。当前版本在保留这些能力的基础上，将单文件终端程序重构为模块化桌面应用，并重点补齐权限、持久化、可观测性、任务可靠性、修改预览和发布能力。

这个项目同时服务于三个目标：

1. 让用户不用打开终端，也能让 Agent 在本地项目中工作。
2. 作为 Coding Agent 架构的学习和实验平台。
3. 作为可继续开发、测试和公开发布的个人项目。

## 2. 当前版本能做什么

### 2.1 桌面工作台

- Windows 桌面界面，蓝白深浅色主题，支持可收起、可拖宽的项目侧栏。
- 项目模式：添加本地目录，在每个项目下建立多条对话，对话默认在该项目内工作。
- 纯聊天模式：没有固定工作目录；需要操作文件时再选择和授权目录。
- 对话支持自动命名、置顶、归档、恢复和删除。
- 消息支持 Markdown、表格、列表、代码块和链接显示。
- 输入区可以选择 Agent/Plan、权限模式、思考强度、Todo 强制模式和验证强度。
- 内置 Prompt 模板、`/` Skill 菜单、工具帮助和可视化新手指南。

### 2.2 Agent 与本地工具

当前向模型提供 27 项工具：

- 工作区工具：`set_working_directory`、`bash`、`read_file`、`list_directory`、`path_exists`、`write_file`、`edit_file`、`delete_file`。
- 规划与能力加载：`TodoWrite`、`task`、`load_skill`、`compress`。
- 后台和持久任务：`background_run`、`check_background`、`task_create`、`task_get`、`task_update`、`task_list`、`claim_task`。
- 团队协作：`spawn_teammate`、`list_teammates`、`send_message`、`read_inbox`、`broadcast`、`shutdown_request`、`plan_approval`、`idle`。

主 Agent 会在“模型回复—工具执行—结果回传”的循环中工作，直到任务有足够的完成证据、被用户取消、需要用户处理、遇到不可恢复错误或达到运行预算。

### 2.3 规划、Todo 与任务板

- Plan 模式先进行只读调查，再生成结构化计划；用户可以批准、修改或取消，批准后才进入实施。
- Todo 是单次任务内的短步骤清单，界面实时显示当前步骤和完成比例。
- Todo 强制模式要求模型先拆出 3–7 步，同一时间只进行一项，并在实际完成后逐项更新。
- 持久任务板适合较长或多人协作任务，支持负责人、状态、依赖、阻塞和领取。

### 2.4 Skill、Memory 与上下文

- Skill Loader 会扫描应用和项目中的 `skills/**/SKILL.md`；输入 `/` 可以搜索并选择 Skill。
- 长期 Memory 自动维护 `user`、`feedback`、`project`、`reference` 四类记忆。每次请求前选择少量相关记忆注入，任务成功后提取可长期复用的信息，数量达到阈值后合并去重。
- 上下文管理保留近期对话和工具结果；旧的大型工具输出会外置并留下摘要、头尾、路径和哈希；上下文过大时生成结构化摘要，同时保留近期窗口。
- `tool_use` 与 `tool_result` 在压缩、恢复和错误修复时保持成对，避免模型 API 因工具协议断裂而拒绝请求。

### 2.5 子 Agent 与多 Agent 协作

- `task` 可以创建一次性子 Agent：Explore 负责只读调查，general-purpose 可以执行一般任务。
- Teammate 是会话内持续存在的协作者，支持创建、分工、领取任务、点对点消息、广播、收件箱、空闲和关停协议。
- UI 可以查看多个子 Agent 或 Teammate 的状态、轮次、当前工具和结果。
- 主 Agent、子 Agent、Teammate 和后台任务共用权限系统与工作区协调器。

### 2.6 权限和工作区安全

系统提供三档权限：

- `safe`：只读和低风险操作自动允许，修改、删除等操作拒绝。
- `approval`：普通操作自动执行，高风险操作向用户申请批准。
- `full_access`：当前工作区内大部分操作无需逐次审批。

三档模式都保留路径边界和关键危险操作拦截。`full_access` 不表示拥有整个电脑的无限权限，也不等同于操作系统级沙箱。

`WorkspaceCoordinator` 让同一时刻只有一个执行者访问文件或运行命令，避免主 Agent、子 Agent、Teammate 和后台任务同时修改工作区。当前优先保证正确性，因此不同文件的只读操作也会串行。

### 2.7 完成判断、验证和恢复

- 系统不会因为模型输出一段纯文本就自动认定文件任务成功，而会根据用户要求检查相应的写入、编辑、删除、命令或委派证据。
- 独立验证分为关闭、标准、严格三档。严格模式可以使用只读工具复查，并在发现明确问题时允许主 Agent 定向修复一次。
- 网络中断、超时或暂时性服务错误会保存可靠检查点；继续任务时先确认结果未知的工具是否已经生效，避免盲目重复写入或删除。
- 非法工具参数、未知工具和断裂的工具消息有协议修复与明确错误记录。
- 运行中再次点击发送按钮会取消模型请求，并终止正在执行的命令进程树。

### 2.8 文件变更、预览和撤销

- 每轮可能写文件的任务会记录文本快照。
- 任务结束后显示新增、修改、删除文件以及增加/删除行数。
- 支持红绿 unified Diff、Markdown 渲染预览、文本预览、打开单文件位置和打开文件夹。
- 可以一键撤销本轮修改；如果任务结束后文件又被外部修改，撤销会拒绝覆盖并提示冲突。
- 可配置任务失败时自动回滚本轮文本文件变化。

### 2.9 持久化、日志与调试

- SQLite 保存项目、对话、消息、完整模型历史、Plan、摘要、运行状态和检查点。
- JSONL 保存会话事件以及每次运行的详细诊断记录。
- 调试模式开启后，任务末尾提供“打开日志”，可直接定位本次运行日志。
- 日志记录模型轮次、停止原因、用量、工具调用、耗时、完成判断、验证结果和异常堆栈；不应记录 API Key 或隐藏思考内容。
- 默认数据位于本机应用数据目录；具体路径和表结构见持久化与诊断文档。

### 2.10 模型、离线测试和发布

- 主流程使用 DeepSeek Anthropic 兼容接口，支持关闭思考及不同思考强度。
- 自动命名使用独立的小请求，当前配置为硅基流动的 `deepseek-ai/DeepSeek-V4-Flash`，失败时回退为用户首条消息截取。
- Fake Client 可以在没有 API Key、没有网络和不产生模型费用的情况下测试工具循环和 UI 协议。
- 项目包含离线自动化测试、真实 DeepSeek CRUD/全功能/Todo/Verifier 测试脚本和脱敏证据。
- 已具备 PyInstaller Python sidecar、Tauri NSIS Windows 安装包、SHA-256 文件和 GitHub Actions 标签发布流程。

### 2.11 保留的终端能力

桌面端是主要入口，但终端 REPL 仍然保留，包括彩色执行跟踪，以及 `/compact`、`/tasks`、`/team`、`/inbox`、`/permissions`、`/visual` 等管理命令。根目录 `s_full.py` 是轻量入口和旧接口兼容层。

## 3. 一次任务如何流转

1. UI 创建一次运行并保存用户消息及本轮配置。
2. sidecar 从 SQLite 恢复该对话的模型历史，修复工具协议，并加入相关 Memory、近期消息、摘要和系统规则。
3. 模型返回文本或工具调用。
4. 工具参数先校验，再经过权限判断和工作区协调器执行，结果写回模型历史和 JSONL 日志。
5. 如果模型继续调用工具，就重复第 3–4 步；Todo、Agent 状态和执行记录同步更新到 UI。
6. 模型给出候选最终答复后，完成判断检查真实工具证据；不够则要求继续。
7. 任务结束时计算文件变化，根据设置运行独立验证或回滚，并保存最终状态和恢复检查点。
8. UI 显示答复、任务状态、文件卡片、Diff/预览、撤销和日志入口。

## 4. 代码结构

| 位置 | 作用 |
| --- | --- |
| `s_full.py` | CLI 轻量入口和旧接口兼容层 |
| `agent_harness/app.py` | 组件装配、主 Agent 循环和 REPL |
| `agent_harness/schemas.py` | 27 项工具的模型 schema |
| `agent_harness/workspace.py` | 文件、PowerShell、后台命令和统一工具执行 |
| `agent_harness/permissions.py` | 风险判断、三档权限和审批缓存 |
| `agent_harness/concurrency.py` | 工作区串行协调锁 |
| `agent_harness/agents.py` | 子 Agent 和 Teammate |
| `agent_harness/state.py` | Todo、Skill、Task、MessageBus 和团队状态 |
| `agent_harness/memory.py` | 长期记忆选择、提取、索引和合并 |
| `agent_harness/context.py` | 工具结果裁剪、摘要和近期窗口 |
| `agent_harness/message_protocol.py` | 工具消息配对、清理与协议修复 |
| `agent_harness/completion.py` | 任务合同分析和完成证据判断 |
| `agent_harness/verifier.py` | 独立验证流程 |
| `agent_harness/planning.py` | Plan V1 生成、持久化和执行 |
| `agent_harness/session_store.py` | SQLite 会话、消息、运行和检查点 |
| `agent_harness/change_tracking.py` | 文件快照、Diff、撤销和回滚 |
| `agent_harness/sidecar.py` | 桌面端 JSONL 协议和事件桥接 |
| `agent_harness/settings.py` | 模型、Provider、环境变量和客户端创建 |
| `agent_harness/naming.py` | 对话自动命名 |
| `agent_harness/fake_client.py` | 离线 Anthropic-compatible Fake Client |
| `agent_harness/tool_validation.py` | 工具参数校验和兼容修复 |
| `desktop/src/` | React 界面、模板、帮助、新手引导、Agent 监视器和 Diff 预览 |
| `desktop/src-tauri/` | Tauri/Rust 窗口、sidecar 管理和系统能力 |
| `tests/` | 离线测试和真实 API 测试入口 |
| `skills/` | 应用内置 Skill |
| `legacy/` | 重构前个人单文件版本，只读快照 |
| `upstream/` | learn-claude-code 上游原版，只读快照 |
| `packaging/`、`release/` | 安装包脚本和发布产物 |

## 5. 数据保存在哪里

应用运行数据默认保存在 Windows 本机应用数据目录。历史版本目录名可能是 `%LOCALAPPDATA%\s_full`，发布版配置使用 `%LOCALAPPDATA%\AstraCode`；实际目录可以通过配置覆盖，因此排查时应先查看当前设置和运行日志给出的真实路径。

主要数据包括：

- `index.sqlite`：项目、对话、消息、模型历史、Plan、摘要和运行状态。
- `sessions/<session-id>/events.jsonl`：该对话的事件流。
- `sessions/<session-id>/runs/<request-id>.jsonl`：单次运行诊断日志。
- `sessions/<session-id>/runtime/`：该会话的任务、团队、Memory 等运行时状态。
- `config.env`：发布版用户模型配置；不得提交到 Git。

详细表结构、消息恢复和压缩边界见 [`architecture/SESSION_PERSISTENCE.md`](architecture/SESSION_PERSISTENCE.md) 与 [`architecture/MESSAGE_CONTEXT_AND_COMPACTION.md`](architecture/MESSAGE_CONTEXT_AND_COMPACTION.md)。日志字段见 [`architecture/AGENT_RUNTIME_AND_DIAGNOSTICS.md`](architecture/AGENT_RUNTIME_AND_DIAGNOSTICS.md)。

## 6. 当前边界

- 权限是应用层风险控制，不是真正的操作系统沙箱。
- 多 Agent 共用一个工作区锁，可靠但并发度有限；没有实现每个 Agent 独立 Git worktree。
- Teammate 的持续性主要限于当前应用会话，应用重启后不会自动恢复正在运行的线程或后台进程。
- 上下文 Token 数是近似估算，摘要忠实度和 Memory 成本仍需长期评测。
- Verifier 可以提高可靠性，但仍然由模型判断，不能替代确定性的编译、测试和静态检查。
- 文件预览和撤销主要面向文本文件；大型文件、二进制文件和复杂图片不是当前重点。
- Windows 安装包尚未进行商业代码签名，macOS/Linux 安装包、自动更新和完整干净机器矩阵仍待完善。
- `s_full_eval.py` 是历史评测分支，不是当前桌面端入口；其中的自测和恢复思想已经被正式模块吸收。

## 7. 想深入某个部分去哪里看

| 想了解的内容 | 文档 |
| --- | --- |
| 产品定位、全部功能、原版与当前版本的能力血缘 | [`product/PRODUCT_DESIGN.md`](product/PRODUCT_DESIGN.md) |
| 每次开发、事故、修复、取舍和技术债 | [`product/PRODUCT_DEVELOPMENT.md`](product/PRODUCT_DEVELOPMENT.md) |
| 后续计划和未完成事项 | [`product/DEVELOPMENT_ROADMAP.md`](product/DEVELOPMENT_ROADMAP.md) |
| 每轮到底传给模型什么、如何压缩 | [`architecture/MESSAGE_CONTEXT_AND_COMPACTION.md`](architecture/MESSAGE_CONTEXT_AND_COMPACTION.md) |
| 上下文模块的设计过程和外部方案调研 | [`architecture/CONTEXT_MODULE_DEVELOPMENT.md`](architecture/CONTEXT_MODULE_DEVELOPMENT.md) |
| SQLite、会话恢复和消息持久化 | [`architecture/SESSION_PERSISTENCE.md`](architecture/SESSION_PERSISTENCE.md) |
| 三档权限的真实边界 | [`architecture/PERMISSION_BOUNDARIES.md`](architecture/PERMISSION_BOUNDARIES.md) |
| Plan V1 的状态和流程 | [`architecture/PLAN_MODE_V1.md`](architecture/PLAN_MODE_V1.md) |
| 完成判定为什么存在、曾修复什么 | [`architecture/COMPLETION_GUARD.md`](architecture/COMPLETION_GUARD.md) |
| 工具消息配对和中断恢复 | [`architecture/TOOL_MESSAGE_PROTOCOL.md`](architecture/TOOL_MESSAGE_PROTOCOL.md) |
| 任务状态、日志和诊断 | [`architecture/AGENT_RUNTIME_AND_DIAGNOSTICS.md`](architecture/AGENT_RUNTIME_AND_DIAGNOSTICS.md) |
| 最新真实模型全功能结果 | [`testing/FULL_FUNCTION_REAL_API_TEST_2026-08-08.md`](testing/FULL_FUNCTION_REAL_API_TEST_2026-08-08.md) |
| Todo 强制模式实测 | [`testing/TODO_MODE_REAL_API_TEST_2026-08-09.md`](testing/TODO_MODE_REAL_API_TEST_2026-08-09.md) |
| Windows 构建和 GitHub 发布 | [`release/GITHUB_RELEASE_GUIDE.md`](release/GITHUB_RELEASE_GUIDE.md) |
| 当前版本发布说明 | [`release/RELEASE_NOTES_0.8.1.md`](release/RELEASE_NOTES_0.8.1.md) |

## 8. 接手时的最短阅读路径

如果要继续开发，按以下顺序阅读即可：

1. 本文，先建立项目全貌。
2. [`product/PRODUCT_DESIGN.md`](product/PRODUCT_DESIGN.md)，确认功能状态和真实边界。
3. [`product/PRODUCT_DEVELOPMENT.md`](product/PRODUCT_DEVELOPMENT.md)，了解历史故障和不可重复踩的坑。
4. 与当前任务对应的 `architecture/` 专题文档。
5. 对照实际模块和测试，不只依赖文档描述。

开发约束由项目根目录 `AGENTS.md` 规定。不要修改 `legacy/` 和 `upstream/` 快照；不要把 API Key、授权头、隐藏思考或敏感工作区内容写入源码、文档、日志证据或提交记录。
