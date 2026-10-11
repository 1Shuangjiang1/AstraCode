# s_full 定制版开发路线

> 文档日期：2026-08-06  
> 当前阶段：桌面端 MVP  
> 原始快照：`legacy/s_full_monolith_2026-08-05.py`，禁止修改

## 1. 项目目标

把目前可在终端运行的模块化 agent，逐步发展成一个面向普通用户的桌面开发助手。用户选择项目文件夹后，可以直接用自然语言下达任务，并在同一个窗口中查看 agent 回复、工具执行、权限审批、计划、文件变化和多 agent 状态。

长期目标不是简单地给终端套一层外壳，而是形成三层稳定边界：

```text
Tauri 2 桌面壳与 React UI
          ↕ JSONL 事件协议
Python agent sidecar
          ↕ 统一执行入口
权限 / 锁 / 文件工具 / 子 agent / teammate
```

这样做可以保留已有 Python agent 能力，同时让桌面 UI、Python 核心和未来的测试工具分别演进。

## 2. 已完成的基础改造

- 原 1365 行 `s_full.py` 已拆分到 `agent_harness/`，原文件已留档。
- 主 agent、子 agent、teammate 共用同一套权限判断和工具执行入口。
- 权限模式支持 `safe`、`approval`、`full_access`。
- 工作区文件与命令访问由进程级协调锁串行化。
- 已有无需 API 的 fake client 和离线单元测试。
- 默认模型配置已预留为 `deepseek-v4-flash`；真实 API Key 等用户提供后再更新。
- 已比对 `s_full_eval.py`：其中有值得回迁的验证轮次、失败恢复和结构化日志，但它是 Terminal-Bench 专用分支，不应整文件覆盖当前版本。

## 3. 桌面端技术方案

### 3.1 选型

- 桌面框架：Tauri 2
- 前端：React + TypeScript + Vite
- agent 后端：现有 Python 包，以长驻 sidecar 进程运行
- 通信：标准输入/输出上的逐行 JSON（JSONL）
- 离线演示：sidecar 内置确定性的 fake 工作流，不需要 API Key

不为本地通信开放 HTTP 端口。Rust 层负责启动和终止 Python 进程、转发命令，并把 sidecar 的事件投递给 React。协议输出只走 stdout，诊断日志只走 stderr，避免破坏消息解析。

开发阶段由 Tauri 直接启动系统 Python。发布安装包阶段再使用 PyInstaller 生成目标平台 sidecar，并切换到 Tauri `externalBin` 打包。

### 3.2 MVP 页面

- 左侧：当前项目、会话列表、创建任务入口。
- 中间：对话和工具事件时间线、任务输入区。
- 顶部：项目和 sidecar 连接状态；Agent/Plan、权限及思考强度放在输入框下方。
- 右侧：本次运行概览、安全边界、未来承载文件 diff、Todo 和 teammate。
- 项目选择器：使用系统原生文件夹对话框。
- 浏览器预览：离开 Tauri 时自动使用前端 demo transport，便于快速调 UI。

### 3.3 MVP 协议

前端发送：

- `hello`：协商协议版本与能力。
- `start_task`：提交项目目录、用户提示、模式、权限、模型、是否离线。
- `cancel_task`：请求取消当前任务。
- `shutdown`：正常终止 sidecar。

sidecar 返回或推送：

- `ready`、`response`：连接与命令确认。
- `session_started`、`status`：会话和阶段变化。
- `assistant_message`：agent 文本结果。
- `tool_started`、`tool_completed`：可审计的工具时间线。
- `plan_created`：MVP 中用于展示 Plan 入口；完整 Plan 引擎属于下一阶段。
- `task_completed`、`task_cancelled`、`error`。

每条消息至少包含 `type`、`timestamp`，任务事件还包含 `request_id` 和 `session_id`。协议版本从 `1` 开始。

## 4. 本轮 MVP 的边界与验收

本轮要完成：

- Tauri 窗口可以启动。
- Python sidecar 随桌面程序启动并完成握手。
- 可以选择项目、输入任务、选择 Agent/Plan 和三种权限模式。
- 离线模式下能完整演示一次任务，显示工具事件和最终回复。
- 关闭或主动停止时可以回收 sidecar。
- Python 协议测试、现有 Python 测试、前端生产构建和 Rust 检查通过。

后续仍未完成：

- 可恢复的多会话持久化。
- 真正的 Plan 审批/执行状态机。
- 实时 diff、文件编辑器、Git 面板。
- 安装包签名与跨平台发行。

这些边界保证 MVP 能基本运行，同时不会用演示逻辑冒充完整 agent 能力。

## 5. 后续功能路线

### 阶段 A：真实 agent 事件化（基础链路已完成）

- 在 Python 核心增加 `EventBus`，替代 UI 对 `print()` 的依赖。
- 增加 `SessionManager`，隔离每个会话的消息、Todo、审批和取消信号。
- [已完成] 将现有 `AgentApp.agent_loop` 接入 sidecar，支持 DeepSeek 在线与 fake 离线两种 client。
- [已完成] 支持 DeepSeek V4 Flash 的关闭思考、High 和 Max，并由所有 agent/client 调用复用。
- [已完成] 完整保留 thinking/tool_use 回传，只安全提取非空 text block。
- [已完成] 支持桌面立即停止、模型连接关闭和活动命令进程树终止。
- 所有工具结果统一为结构化对象，保留摘要、耗时、风险和可展示详情。

### 阶段 B：桌面权限审批

- 增加异步 `ApprovalBroker`，权限引擎不再直接调用终端 `input()`。
- UI 显示风险原因、精确命令/路径、执行者和影响范围。
- 用户可选择仅本次允许、同类操作本会话允许、拒绝。
- 子 agent 和 teammate 继续复用同一个 broker、权限策略和审计记录。
- 权限预设可按项目保存，但关键危险操作仍保持硬拦截。

### 阶段 C：完整 Plan 模式

> 2026-08-07：Plan V1 已完成只读探索、结构化计划、SQLite 持久化、批准/修改/取消和批准后执行。步骤级实时进度与自动 REPLANNING 留待 V2，详见 [`PLAN_MODE_V1.md`](../architecture/PLAN_MODE_V1.md)。

参考主流 coding agent，Plan 模式采用显式状态机：

```text
NORMAL → PLANNING → WAITING_FOR_REVIEW
                        ↓ approve / revise
                    EXECUTING → VERIFYING
                         ↑          ↓ fail
                         └── REPLANNING
```

- 规划阶段只开放读取、搜索、目录浏览等只读工具。
- 计划使用结构化步骤，包含目标、依据、预计修改、风险、验证方式和状态。
- 用户可以批准、提出修改或取消；未经批准不得进入写入阶段。
- 执行时持续更新步骤状态，出现事实变化时回到重新规划而不是静默偏离。
- 简单任务允许轻量计划，但仍保存决策与验证结果。

### 阶段 D：回迁 eval 分支能力

从 `s_full_eval.py` 选择性迁移：

- 任务结束前的强制验证轮次。
- 工具失败后的恢复提示和有限重试。
- [V1 已完成] 文件改动完成判据，防止只描述不执行；通用验收策略仍待继续扩展。
- JSONL 审计日志和每轮摘要。

不迁移 Terminal-Bench/Docker 专用路径、提示词和适配器假设。验证能力应进入通用 `VerificationPolicy`，由 CLI、桌面端、主 agent 和 teammate 共同使用。

### 阶段 E：文件体验与多 agent

- 文件树、变更列表、diff 查看与逐项接受/回滚。
- Todo/Plan 面板与任务耗时。
- teammate 状态、消息和工作区锁等待情况可视化。
- 从“整个工具调用持锁”升级为按规范化路径的读写意图调度；在正确性验证完成前，写操作仍保持单写者策略。

### 阶段 F：发布

- PyInstaller 构建 Python sidecar。
- Tauri `externalBin`、能力白名单和最小系统权限。
- Windows 安装包、自动更新、崩溃恢复、日志导出。
- API Key 使用系统安全凭据存储，不写进项目 `.env`。

## 6. 开发约定

- `legacy/` 和 `upstream/` 只用于比较，禁止在其上继续开发。
- 新桌面代码放在 `desktop/`，Python 协议仍归 `agent_harness/`。
- 协议字段只能向后兼容地增加；破坏性变更必须提升协议版本。
- 所有新功能先提供 fake/offline 测试路径，再连接真实模型。
- UI 不直接执行文件或命令；所有能力必须经过 Python 的权限和协调层。
- 不在日志、事件或界面中返回 API Key、完整环境变量或其他秘密。

## 7. 建议的下一轮顺序

1. 把真实 `AgentApp` 接进 sidecar 事件流。
2. 实现桌面审批 broker，完成需要审批的真实工具调用。
3. 实现 Plan 状态机和计划审阅界面。
4. 回迁 eval 的验证/恢复策略。
5. 增加文件 diff 与会话持久化。
6. 最后处理 PyInstaller、安装包与签名。

## 8. 2026-08-06 命令卡住与删除误报修复

现象包括：选择项目外工作目录后命令失败；文件已经创建或删除，但模型继续发起 `bash`；删除后的“不存在”检查以退出码 1 显示为执行失败；含中文输出的命令可能污染日志。

根因不是 DeepSeek tool-use 参数漏传。Anthropic 兼容链路已完整回传 assistant 的 thinking、text、tool_use，并用匹配的 tool-use ID 回填 tool_result。主要问题在本地工具语义：名为 `bash` 的工具在 Windows 实际落到 `cmd.exe`，schema 又没有声明 shell 方言；基础文件操作只能借助命令行，模型容易把“文件不存在”的正常结果当作失败后重试；桌面最终答案后还同步执行隐藏的记忆请求，造成视觉上的延迟。

已完成：

- Windows 命令固定为非交互 PowerShell，声明正确方言，并统一 UTF-8 输出。
- 工具子进程的 stdin 固定为 `DEVNULL`，不继承桌面 sidecar 的长期输入管道，修复简单 Python 命令固定卡到 30 秒的问题。
- 使用真实 DeepSeek 和保持 stdin 打开的真实 sidecar 长连接回归：`python 394_string_decode.py` 工具耗时 809ms，完整任务 4.98s 结束。
- 单条命令默认 30 秒超时，禁止在未明确要求时启动 watcher、server 或交互进程。
- 新增 `list_directory`、`path_exists`、`delete_file`，主 agent、子 agent 和 teammate 共用。
- `delete_file` 对已不存在文件返回成功；同一失败工具调用连续出现时有限抑制。
- system prompt 要求成功修改后最多做一次有效验证，随后结束。
- 桌面事件显示实际命令/路径和耗时；最终答案后跳过同步记忆整理。
- 在 `<TEST_ROOT>` 的项目外隔离目录完成工具层 CRUD 和真实 DeepSeek 创建/执行/删除回归，之后删除测试目录。

该问题在下一节记录的 0.2.0 中已补齐桌面 `ApprovalBroker`；后续工作转为审批历史审计和更细粒度的策略配置。

## 9. 2026-08-06 工作空间与设置中心（0.2.0）

本阶段已完成：

- GFM Markdown 安全渲染，不启用原始 HTML。
- 项目模式：添加多个项目，每个项目管理多条独立对话，任务默认在项目沙箱内执行。
- 聊天模式：无初始工作目录，普通对话不触发文件工具；文件任务先通过 `set_working_directory` 选择目录。
- 桌面 `ApprovalBroker`：sidecar 发出 `approval_required`，UI 支持拒绝、仅本次允许、本会话同类允许，任务线程等待决定后继续。
- 会话内后端历史保留，同一对话的连续请求可以复用模型上下文；聊天会话也会记住已批准的活动目录。
- 深色、浅色、跟随系统主题；项目、会话、消息和运行偏好本机持久化。
- 设置中心可以安全替换 DeepSeek API Key、模型 ID、Base URL、命令超时，并读取实时工具清单。
- 主 Agent、子 Agent 和 teammate 均通过统一 `ToolExecutor` 使用目录切换与权限判断。

验证：28 项 Python 测试通过，React/TypeScript 生产构建通过；真实 DeepSeek 聊天模式在审批后切换到 `<TEST_ROOT>\codex_rw_test`，随后完成只读目录检查并正常结束，全程未写入文件。

下一阶段建议：把前端会话消息从 localStorage 迁移为项目级 SQLite/JSONL 存储，并为项目删除、会话重命名和历史清理增加显式 UI。

## 10. 2026-08-06 侧边栏与视觉修整（0.2.1）

- 修复浅色模式输入区外层仍使用深色固定渐变的问题，并补全浅色消息文字与控件颜色。
- 建立小、中、大三档圆角规范，覆盖导航、会话卡片、执行记录、设置和审批弹窗。
- 工作空间切换移到侧边栏顶部；项目模式显示项目树，项目旁可直接新建所属对话，纯聊天模式显示独立聊天列表。
- 会话基础记录增加 schema 版本、更新时间、运行状态、模型、权限、思考强度和项目路径，旧 localStorage 数据自动兼容。
- 会话磁盘持久化的调研和 SQLite + JSONL + checkpoints 方案见 [`SESSION_PERSISTENCE.md`](../architecture/SESSION_PERSISTENCE.md)。

## 11. 2026-08-06 会话数据库与上下文恢复（0.3.0）

- 新增 Python `SessionStore`，使用 WAL 模式 SQLite 保存项目、会话、可见消息、完整事件与模型原始历史。
- sidecar 任务事件同步追加到每个 session 的 `events.jsonl`；旧 localStorage 数据在数据库为空时自动导入。
- Agent 与 Plan 模式都按 session ID 恢复多轮上下文，应用重启后仍可继续；不同对话严格隔离。
- 自动压缩保留最近轮次，将连续性摘要、完整 transcript 路径和 token 估算写入数据库，并在 UI 展示压缩事件与摘要。
- 项目对话和纯聊天支持置顶、归档、恢复与确认后永久删除；置顶会话优先排序，归档会话从默认侧边栏隐藏。
- 具体消息组装、压缩边界、数据库表和安全约束见 [`SESSION_PERSISTENCE.md`](../architecture/SESSION_PERSISTENCE.md)。

验证：32 项 Python 测试、React/TypeScript 生产构建和 Tauri `cargo check` 全部通过；浏览器视觉回归同时发现并修复了 `library_saved` 被误计入任务时间线而循环保存的问题。测试数据库使用逐用例隔离目录，正式数据库未写入任何合成会话。
