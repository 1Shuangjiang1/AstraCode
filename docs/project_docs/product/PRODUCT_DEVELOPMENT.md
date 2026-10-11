# AstraCode Workbench 产品开发档案

> 文档目的：记录项目如何演进、曾经出现什么问题、根因是什么、修复落在哪里，以及未来如何继续排障。
>
> 当前版本：0.8.1；更新时间：2026-10-11。

## 1. 接手时先看什么

推荐阅读顺序：

1. [`PRODUCT_DESIGN.md`](PRODUCT_DESIGN.md)：产品目标、功能状态和路线图；
2. [`PERMISSION_BOUNDARIES.md`](../architecture/PERMISSION_BOUNDARIES.md)：权限实际边界与缺口；
3. 本文：架构、事故和排障方式；
4. [`CONTEXT_MODULE_DEVELOPMENT.md`](../architecture/CONTEXT_MODULE_DEVELOPMENT.md)：上下文策略；
5. [`COMPLETION_GUARD.md`](../architecture/COMPLETION_GUARD.md)：完成判定；
6. [`TOOL_MESSAGE_PROTOCOL.md`](../architecture/TOOL_MESSAGE_PROTOCOL.md)：工具调用协议；
7. [`FULL_FUNCTION_REAL_API_TEST_2026-08-08.md`](../testing/FULL_FUNCTION_REAL_API_TEST_2026-08-08.md)：真实 DeepSeek 全功能验收。

## 2. 当前代码结构

```text
s_full_custom_dev/
├─ agent_harness/
│  ├─ app.py                 # 主 Agent 工具循环和完成门
│  ├─ sidecar.py             # 桌面 JSONL 协议、任务、审批、设置
│  ├─ settings.py            # DeepSeek 和运行配置
│  ├─ session_store.py       # SQLite、事件和运行日志
│  ├─ permissions.py         # 风险分级与三档权限
│  ├─ workspace.py           # 文件、PowerShell、工作区执行
│  ├─ planning.py            # Plan V1
│  ├─ context.py             # 上下文预算与工具结果压缩
│  ├─ completion.py          # 任务完成证据与状态机
│  ├─ message_protocol.py    # tool_use/tool_result 修复
│  ├─ tool_validation.py     # 工具参数 schema 校验
│  ├─ memory.py              # 长期记忆检索、提取、索引和合并
│  ├─ state.py               # Todo、任务板、Skill、消息总线和原子写入
│  ├─ concurrency.py         # 主/子/队友/后台共享工作区协调
│  ├─ naming.py              # 低成本对话自动命名
│  ├─ agents.py              # 子 Agent 和 Teammate
│  ├─ verifier.py            # 标准/严格独立验证
│  ├─ change_tracking.py     # 文本检查点、Diff、撤销和冲突保护
│  ├─ ui.py                  # 终端追踪与文本提取
│  └─ fake_client.py         # 离线模型
├─ desktop/
│  ├─ src/App.tsx            # 主界面和状态管理
│  ├─ src/styles.css         # 明暗主题和组件样式
│  ├─ src/transport.ts       # Web/Tauri bridge
│  └─ src-tauri/src/main.rs  # sidecar 进程与本地受限命令
├─ tests/                    # 自动化与真实 API 测试
├─ legacy/                   # 原始单文件备份
├─ upstream/                 # learn-claude-code 原版
└─ docs/project_docs/        # 统一设计、协议、事故与测试文档中心
```

## 3. 运行链路

1. React 调用 `WorkbenchBridge.send()`。
2. Rust 把 JSON 写入 Python sidecar 标准输入。
3. sidecar 校验命令、写用户消息、建立单次运行日志。
4. `AgentApp` 构建系统提示、上下文和工具 schema。
5. DeepSeek 返回文本、thinking 和/或 tool_use。
6. 参数校验 → 权限判断 → 工作区锁 → 工具执行。
7. tool_result 回传模型，直到完成门接受或进入其他终止状态。
8. sidecar 保存模型历史并向 UI 发事件。
9. UI 更新 Markdown、执行记录、计划、标题和状态。

### 3.1 原始 `s_full.py` 完整基线

2026-08-10 重新逐段审计 `agents/s_full.py`（1365 行），确认它不是只有 Agent Loop 的空壳，而是合并了 learn-claude-code s01–s11 的多数机制。此前产品文档只用“Todo、任务、技能、后台任务”等短语概括，遗漏了 Memory、消息协议和任务板细节，容易造成两种错误理解：一是误以为这些功能已经丢失；二是把原版能力误写成当前版本从零原创。

原始单文件的完整能力如下：

1. **主 Agent 循环**：系统提示、模型调用、tool_use 分发、tool_result 回填、最大轮数和最大耗时。
2. **23 项工具**：4 个文件/命令工具、Todo、子 Agent、Skill、手动压缩、2 个后台工具、4 个任务板工具和 9 个团队协作工具。
3. **基础权限**：危险命令 deny-list、工作区逃逸检查和终端询问。
4. **TodoManager**：短清单、状态校验、最多一项进行中、长时间不更新时提醒。
5. **Subagent**：Explore 与 general-purpose 两类一次性委派。
6. **SkillLoader**：扫描 `skills/**/SKILL.md`，解析 frontmatter 和按名称加载正文。
7. **上下文压缩**：旧工具结果裁剪、100k 阈值自动摘要、手动 `compress`、压缩前 transcript 落盘。
8. **TaskManager**：JSON 持久任务，支持创建、读取、更新、列表、删除、负责人、依赖与解除依赖。
9. **BackgroundManager**：守护线程执行命令、状态查询、完成通知回注下一轮上下文。
10. **MessageBus**：JSONL 收件箱、点对点消息、广播和读取后清空。
11. **TeammateManager**：持久成员身份、角色/状态、工具循环、收件箱唤醒、idle、自动领取可执行任务和超时关闭。
12. **团队协议**：shutdown request_id 握手、队友计划批准/拒绝、lead/teammate 消息类型。
13. **Memory**：`user/feedback/project/reference` 四类 Markdown 记忆、`MEMORY.md` 索引、相关记忆选择、关键词降级、任务结束自动提取、达到阈值后的合并去重。
14. **终端可观测性**：中文彩色阶段日志、输入输出预览、`/compact /tasks /team /inbox /visual` REPL 命令。

原文件开头明确写明 s12 的“task-aware worktree isolation”单独教学，不属于 `s_full.py`。当前版本也没有实现每个 Agent 独立 worktree，而是采用统一 `WorkspaceCoordinator` 串行工作区访问。因此简历和面试不得宣称项目已具备 worktree 隔离。

### 3.2 `s_full_eval.py` 历史实验分支

`s_full_eval.py` 不是功能更多的正式运行入口，而是面向 benchmark 的实验变体：它主动禁用 Memory，增加完成前检查/自测提示、可恢复失败识别、替代路径提示和验证轮次。0.8.1 已将这些实验思路升级为确定性 `CompletionGate`、可选独立 `Verifier`、运行状态机和安全恢复；因此该文件保留为历史对照，不应继续作为当前产品入口。

### 3.3 当前版本对原始能力的保留方式

| 原版组件 | 当前模块 | 主要变化 |
| --- | --- | --- |
| Agent loop / tool dispatch | `app.py`、`schemas.py`、`tool_validation.py` | 23 项扩为 27 项，增加参数校验、完成证据、取消和事件 |
| Permission | `permissions.py`、`workspace.py` | 三档风险策略；主/子/队友统一入口 |
| Todo | `state.py` + sidecar/UI | 增加强制 3–7 步状态机和可视化 |
| Task board | `state.py:TaskManager` | 原子写入、按会话 runtime 隔离，语义基本保留 |
| Skill | `state.py:SkillLoader` | 内置与项目目录合并，项目同名优先，UI `/` 入口 |
| Context | `context.py` | 工具结果 artifact、结构化摘要、近期窗口和请求预算 |
| Background | `workspace.py:BackgroundManager` | 复用统一 PowerShell、权限和工作区协调器 |
| Message bus | `state.py:MessageBus` | 按会话 runtime 隔离并向桌面发送观测事件 |
| Subagent / Teammate | `agents.py` | 权限复用、工作区串行、协议修复和 UI 监视 |
| Memory | `memory.py:MemoryStore` | 自动检索/提取/合并完整保留，数据从项目目录迁到会话 runtime |
| Visual REPL | `ui.py`、`app.py:repl` | 保留终端兼容入口，并新增权限切换命令 |

## 4. 开发演进与问题记录

### 4.1 从教学单文件到可维护项目

初始状态：主要逻辑集中在 `s_full.py`，大量复用 learn-claude-code 原版。

调整：

- 保存原始单文件到 `legacy/`；
- 保存上游版本到 `upstream/`；
- 拆分配置、权限、工作区、Agent、状态、记忆和 UI；
- 建立 README 和开发路线文档。

### 4.2 权限、子 Agent 与并发

需求：安全、审批、完全访问三种模式，并让子 Agent/Teammate 复用。

实现：

- `PermissionEngine` 统一风险分类和批准缓存；
- `ToolExecutor` 成为所有执行者的共同入口；
- `WorkspaceCoordinator` 保证单一执行者访问工作区；
- 审批输入使用串行锁。

遗留：权限是规则分类器而非 OS 沙箱，详见权限文档。

### 4.3 Fake Client

增加 Anthropic 风格的离线响应队列，可脚本化文本和工具调用。用于验证工具循环、权限、Plan、取消和完成判定，不消耗 API。

### 4.4 DeepSeek V4 Flash 接入

当前使用官方 Anthropic-compatible endpoint：

```text
https://api.deepseek.com/anthropic
```

支持：

- 模型 `deepseek-v4-flash`；
- thinking enabled/disabled；
- Anthropic `output_config.effort=high/max`；
- 工具调用和多轮 thinking 回传。

配置保存在被 Git 忽略的 `.env`。API Key 不应写进文档或日志。

### 4.5 Tauri 2 桌面 MVP 与启动器

选择 Tauri 2 + React 前端、Python sidecar。增加双击批处理和 PowerShell 启动脚本。

曾出现“命令框闪退但桌面不显示”：启动器缺少依赖检查和错误保留。修复为显式检查 npm/cargo、失败时保留提示，并让 sidecar 作为隐藏子进程运行。

### 4.6 DeepSeek 工具结果 `None` 拼接异常

症状：`can only concatenate str (not "NoneType") to str`。

根因：Windows 子进程在异常/中止路径可能返回 `stdout=None` 或 `stderr=None`，旧代码直接相加。

修复：所有输出先标准化为空字符串，再组合；工具结果统一转成字符串。

### 4.7 PowerShell/Python 命令无故等待 30 秒

症状：`python -c "print('hello')"` 已输出但被判定 Timeout。

根因：桌面 sidecar 的标准输入管道被工具子进程继承，导致 PowerShell/原生子进程保持句柄，`communicate()` 无法观察到完整 EOF。

修复：命令使用 `stdin=DEVNULL`，Windows 新进程组，轮询退出，取消时结束进程树。真实 CRUD 和命令测试通过。

### 4.8 数据库、项目树和对话管理

增加 SQLite：项目、会话、消息、模型历史、事件、计划。实现项目/聊天侧边栏、置顶、归档、恢复和删除。

删除会话会同时删除：

- SQLite 会话相关数据；
- 内存模型历史；
- 审批缓存；
- `%LOCALAPPDATA%\s_full\sessions\<session-id>` 日志目录。

### 4.9 上下文模块

目标：保留关键约束和近期工具结果，压缩大而旧的输出。

实现：

- 估算 messages/system/tool schema/output reserve；
- 老旧大工具结果保存原文到 artifact，再在上下文中放摘要和路径；
- 达到阈值时生成结构化摘要；
- UI 显示摘要和估计 Token。

### 4.10 Plan V1

计划阶段只读调查，生成结构化 JSON，再进入等待审阅。支持批准执行、要求修订、取消，计划和版本写入数据库。

### 4.11 “只说要做，但任务直接结束”

症状：模型读取文件后回复“现在我来编写”，没有写文件，任务却标记完成。

根因：旧循环把 provider 的纯文本 `end_turn` 等同于任务完成。

修复：`CompletionGate` 从用户请求推导 inspection/mutation/command 证据；没有成功工具证据、空答复、被截断或只有未来时态时继续运行。多次仍不满足则标记 incomplete，不伪装完成。

### 4.12 结构化运行日志和执行记录折叠

增加：

- 会话 `events.jsonl`；
- 每次请求独立 `runs/<request-id>.jsonl`；
- 模型调用时长、stop reason、Token、工具结果和 traceback；
- UI 执行记录展开/收起。

### 4.13 孤立 `tool_use` 导致 HTTP 400

症状：DeepSeek 报 `tool_use ids were found without tool_result blocks immediately after`。

根因：用户在工具执行中取消，assistant tool_use 已写入历史，但函数在追加 user tool_result 前返回并保存。

修复：

- 取消时为同一轮所有工具补齐真实或中断结果；
- API 调用前自动修复旧历史；
- 数据库保存前再次修复；
- tool block 的实际存在优先于不可靠的 stop reason；
- 当前损坏会话已迁移，并保留数据库备份。

### 4.14 `max_tokens` 截断出空 `write_file` 参数

症状：`write_file` 缺少 `path` 和 `content`。

根因：高思考请求用满旧的 8000 Token，只输出工具名，JSON 参数未完成；SDK暴露为空对象。

修复：

- `S_FULL_MAX_OUTPUT_TOKENS` 默认 32768；
- API timeout 300 秒；
- 通用工具参数校验；
- 截断回包增加简洁重试指令；
- 子 Agent、Teammate 和 Plan 复用输出预算。

真实 DeepSeek 高思考 CRUD：创建、读取、修改、读取、删除、检查不存在全部通过；9 次模型调用，0 API 失败。

### 4.15 调试模式与日志入口

新增顶栏调试按钮。开启后，任务结束区域显示本次日志路径和“打开日志”。Tauri 只允许资源管理器定位应用日志根目录内的文件，避免通用任意路径启动能力。

### 4.16 自动对话命名

旧行为：首条消息机械截取 24 字符。

初版行为：

- 首轮使用 `S_FULL_TITLE_MODEL`；
- 默认复用 V4 Flash 和主任务 Key；
- 关闭 thinking、无工具、最多 48 Token；
- 失败回退到本地稳定短标题；
- `session_title_updated` 同步数据库和 UI。

真实请求生成标题成功。

### 4.17 自动命名迁移到硅基流动

为降低主任务与辅助能力互相影响的风险，命名链路改为独立供应商配置：

- 接口：`https://api.siliconflow.cn/v1/chat/completions`；
- 模型：`deepseek-ai/DeepSeek-V4-Flash`；
- 请求格式：OpenAI-compatible Chat Completions；
- `enable_thinking=false`、无工具、`max_tokens=48`；
- 新增 `S_FULL_TITLE_BASE_URL` 与 `S_FULL_TITLE_API_KEY`；
- 命名凭据只从应用配置目录读取，不接受所选项目 `.env` 覆盖，避免项目重定向命名请求；
- 主 Agent 继续使用原 DeepSeek Anthropic-compatible Base URL 与 Key；
- 命名在后台线程运行，失败时发出 `title_generation_failed` 并使用本地标题，不中断主任务。

验证结果：真实硅基流动请求约 2 秒生成“修复任务后标题生成问题”；随后使用原配置完成一次真实 DeepSeek 主模型请求，两条链路均成功。

### 4.18 真实 DeepSeek 全功能验收与完成合同修复

新增可重复运行的 `tests/live_deepseek_full_suite.py`，覆盖 CRUD、Todo、持久任务、Skill、单/多子 Agent、双 teammate、后台任务、Plan、聊天目录、权限和自动命名。

第一轮 5/10 暴露完成合同的跨对象误判、角色局部只读被全局化、Shell 绕过、委派写入证据缺失、Plan 执行残留只读请求，以及外部项目无法加载内置 Skill。完成以下修复：

- 文件意图不跨标点，不穿过任务/计划/清单对象；
- 角色局部只读与全局只读分离；
- 只读合同同步拦截 PowerShell 写入命令；
- 委派成功并检查文件可作为 delegated mutation 证据；
- Plan 执行提示去除 planning-only 原始请求；
- SkillLoader 合并应用内置和项目本地 Skill，项目同名版本优先。

最终真实套件 10/10，通过 51 次可追踪主/Plan 模型调用、3 个子 Agent、2 个 teammate，主/Plan API 失败为 0。详见 [`FULL_FUNCTION_REAL_API_TEST_2026-08-08.md`](../testing/FULL_FUNCTION_REAL_API_TEST_2026-08-08.md)。

### 4.19 AstraCode 品牌、侧栏与任务辅助界面

本轮将可见产品名从 `s_full Workbench` 调整为 `AstraCode Workbench`，同时保留 `%LOCALAPPDATA%\s_full`、`sfull.*` localStorage 键和 Python 入口，避免旧会话、Key 和日志失效。

完成内容：

- UI 改为蓝白视觉系统，浅色和深色均使用同一套蓝色语义色；
- 项目侧栏支持 220–420px 拖拽宽度、66px 收起态和缓动动画，宽度与状态本地持久化；
- 会话标题固定一行，尾部渐隐，悬停使用原生 tooltip 显示全文；
- 输入框增加数据驱动的 Prompt 模板菜单；
- sidecar 增加 `get_skills`，输入 `/` 可搜索实际 Skill 目录；选择后本轮明确要求模型先调用 `load_skill`；
- TodoWrite 成功后发出 `todo_updated`，右栏展示进度和当前步骤；
- 子 Agent/Teammate 运行时发出开始、轮次、文本、工具、完成/失败事件；右栏显示摘要，监视器支持多个 Agent 切换查看；
- Todo 和 Agent 监视数据写入 SQLite `sessions.ui_state_json`，重启后可恢复；
- 新增 [`MESSAGE_CONTEXT_AND_COMPACTION.md`](../architecture/MESSAGE_CONTEXT_AND_COMPACTION.md)，按真实实现记录每轮消息、工具协议修复和两级压缩。

安全边界：监视器只展示 Agent 的任务、可见文本、工具名/结果摘要和状态，不展示隐藏思维链。

验证：前端生产构建通过；数据库、权限复用、sidecar 与 Agent 事件共 16 项定向测试通过；完整 Python 回归 66 项通过。真实 DeepSeek 全功能回归结果记录在本轮测试报告。

### 4.20 Verifier、修改事务与中断恢复立项

2026-08-09 用户要求把三项工程能力作为下一阶段：可选独立 Verifier、文本 Diff/撤销/失败回滚、以及网络或用户中断后的可靠恢复。

先确定以下约束：

- Verifier 必须和当前基于工具证据的 CompletionGate 分层，不能用第二个模型的一句话替代客观证据；
- 用户可在输入框下选择关闭、标准或严格验证，简单任务允许关闭；
- 修改预览和撤销不能依赖 `git reset --hard`，因为工作区可能已有用户未提交内容；
- 每轮任务在首次写入前保存受影响文件的原始状态，记录新增、修改、删除、行数变化和文本 Diff；
- 失败自动回滚应可配置，并且只恢复本轮由 Agent 触及的路径；
- 恢复时区分安全重试与不安全重放：读取和确定未执行的工具可继续，已经开始但结果未知的命令必须标记为“需用户确认/重新检查”；
- 所有状态、验证结论和恢复动作写入运行 JSONL 与 SQLite，UI 显示明确终态。

同时新增项目级 `AGENTS.md` 和 `.memory/development-documentation-policy.md`，持久化“每次开发必须更新产品设计和产品开发文档”的用户要求。

### 4.21 Verifier、变更事务与中断恢复 V1 落地

本轮新增：

- `agent_harness/verifier.py`：独立、只读 Verifier。关闭模式零调用；标准模式一次结构化判断；严格模式最多 5 轮只读调查，结论为 `pass / needs_fix / blocked`。严格模式发现可修复问题时，主 Agent 最多进行一次定向修复和复验。
- `agent_harness/change_tracking.py`：不依赖 Git 的本轮文本事务。首次可能修改前保存原文件，结束扫描新增/修改/删除，生成 unified Diff、预览和行数统计；撤销前比较任务结束时哈希，保护任务后用户的手动修改。
- SQLite schema v3 的 `runs` 表：保存运行状态、阶段、原始请求、配置、最后事件、进行中/已完成工具、变更集、验证结果和可恢复标记。
- sidecar 新命令：`get_recovery`、`resume_task`、`dismiss_recovery`、`get_change_set`、`undo_run`。
- 暂时性错误分类：超时、连接异常、429、502/503/504 等进入 `task_interrupted`，保留现场；确定性失败默认只回滚本轮捕获的文本文件。
- Plan 审批后执行现在也创建独立 run，并继承验证档位与失败回滚配置。
- UI 输入框增加验证档位；对话区增加验证结论、文件变化卡片、Diff/最终文本弹窗、一键撤销和安全继续卡片。

重要边界：V1 跟踪 UTF-8/常见文本文件，单文件上限 2 MB；二进制、超限文件、Shell 对数据库等外部副作用不会被事务恢复。它是 Git 的补充，不是替代。

测试过程发现两个测试问题并保留失败证据：首次真实验收把运行状态目录放在被测工作区内，污染变更集；第二次模型没有遵循宽泛写文件请求，严格 Verifier 正确判为 `needs_fix`。修正隔离位置并明确工具任务后最终通过。没有把 Verifier 的正确失败伪装成系统成功。

最终验证：

- Python 全量回归：73 passed；取消命令的 Windows 句柄回归另连续运行 8 次通过；
- 前端生产构建：通过；
- Tauri Rust `cargo check`：通过；
- 既有真实 CRUD：创建、修改、删除全部通过，10 次模型调用、0 API 失败、0 无效工具结果；
- 新真实验收：主 Agent 创建教程、严格 Verifier 只读复核、Diff 统计、一键撤销、重启恢复检查点 5/5 通过，临时工作区与运行状态目录均已清理；
- 脱敏证据：`testing/evidence/verifier_changes_recovery_20260809_025730.json`。

最终全量回归还捕获到 Windows 取消命令后的目录句柄偶发未释放：`cancel_active` 与 `bash` 轮询线程会同时终止同一进程树。修复为由取消事件唤醒命令所属线程，统一执行一次进程树终止、等待和管道回收，避免竞态与工作目录锁定。

设计依据采用官方文档：Claude Code checkpointing/rewind、Claude Agent SDK file checkpointing、OpenAI Codex 的测试与 Diff 审阅、VS Code Diff/Source Control、LangGraph persistence/interrupt/fault tolerance。共同结论是：检查点应持久化、恢复应从稳定边界开始、未知副作用不可盲目重放、Diff 和验证证据必须对用户可见。

### 4.22 Prompt 模板大编辑器与通用模板扩充

原交互在选择模板后立即把长文本放进高度较小的主输入框，用户需要在输入框内频繁滚动才能补充内容。本轮将 `PromptTemplateMenu` 改为弹窗内两阶段状态：

1. 浏览态按 8 个分类显示模板卡片；
2. 选择后原弹窗扩展为大文本编辑器，用户修改草稿；
3. 只有点击“确认填入”才把编辑结果交给 `App`，取消或返回不会改变主输入框。

实现细节：

- `PromptTemplateMenu.tsx` 内部维护选择项、草稿和分类，不把半成品提升到全局状态；
- 编辑器自动聚焦，显示字符数，提供返回、关闭、取消和确认操作；
- `Esc` 在编辑态返回列表、在浏览态关闭，避免一次按键丢失整个操作位置；
- 弹窗编辑态最大约 720px 宽、620px 高，正文区域自适应占满剩余空间；窄屏退化为单列模板列表；
- `promptTemplates.ts` 从 7 个模板扩充到 15 个，新增学习、写作、分析和规划四类非代码场景；
- 修复视觉验收中发现的颜色变量错误：项目实际蓝色语义变量仍名为 `--orange`，确认按钮若使用不存在的 `--blue` 会呈透明背景，已改为现有主题令牌。

验证：TypeScript 检查和 Vite 生产构建通过；浏览器实际完成“打开模板 → 选择学习路线 → 在大编辑器修改 → 确认填入”流程，主输入框得到完整编辑结果，弹窗关闭，控制台 0 error。

### 4.23 Todo 快捷模式、Todo 模板与紧凑 Verifier 提示

完成内容：

- `promptTemplates.ts` 新增“Todo 分步执行”模板，模板总数增至 16；
- Composer 增加 `Todo` 按钮，使用 `aria-pressed` 和主题高亮表示本轮启用；
- `startTask` 组合 Skill 与 Todo 两类执行要求，不再让两者互相覆盖；Todo 约束只进入模型 prompt，可见消息仍保存用户原文；
- 明确要求 TodoWrite 只负责进度，不能替代 `write_file/edit_file/bash` 等实际工具，防止模型把维护清单误当作完成任务；
- 发送后清除 Todo 模式，下一轮默认不继承；
- 原独立验证大卡片改成原生 `details/summary` 紧凑提示，折叠高度实测约 28px，点击后才显示摘要和 issues。

界面验证：Todo 按钮开启时 `aria-pressed=true` 且高亮；规划分类中可找到 Todo 模板；任务发送后按钮恢复 false；紧凑验证提示折叠高度 28px、文字为“验证通过 / STANDARD”，浏览器控制台 0 error。

真实 DeepSeek 测试没有伪装为成功：三次隔离运行均实际触发 TodoWrite（5、5、3 次），第三次也创建并回读了两个目标文件，但模型选择 Bash 代替指定的 `write_file`，且未关闭全部 Todo，最终达到 round limit。相关脱敏失败证据为 `forced_todo_20260809_122927.json`、`forced_todo_20260809_123156.json`、`forced_todo_20260809_123504.json`。当前能力因此标记为 Beta；后续应把“Todo 必须关闭”和“允许的实际工具”升级为宿主侧状态机约束，而不只依赖提示词。

### 4.24 Todo 模式只读误判事故与宿主状态机

用户日志 `a54638ee-5eb9-4820-b7a4-a09ef0b8b87f.jsonl` 显示：模型已经建立 4 项 Todo，并完成目录和文档读取，但 `write_file` 两次、带写入意图的 `bash` 一次均被 `tool_blocked_by_task_contract` 拦截，最终达到 8 轮上限。运行合同错误地记录为 `action_oriented=false`，并禁止 `write_file/edit_file/delete_file`。

根因不是 DeepSeek API 参数，而是 UI 注入的 `<execution-requirements>` 含有“TodoWrite 不能代替 write_file、edit_file、bash”这句话。完成门把整段宿主提示当成用户原话，否定词规则将其误判为“用户禁止写文件”；同时 Todo 按钮只靠提示词，sidecar 不知道本轮是 Todo 模式，无法阻止未关闭清单就结束，也没有为多次“实际工作 + 更新清单”预留足够轮次。

修复内容：

- `completion.py` 在推断任务合同前移除宿主生成的 execution/recovery/verifier 控制块，并识别“在文档里面写……”这类“目标在前、动作在后”的中文写入表达；
- `App.tsx` 发送 `display_prompt` 和显式 `todo_mode`，可见消息不再落盘为内部包装文本；
- `sidecar.py` 将 Todo 模式写入 run config、恢复请求和 `session_started` 日志，并传给 `AgentApp`；
- `AgentApp` 强制首个任务工具为合法 `TodoWrite`，要求 3–7 项、未完成时恰好一项 `in_progress`，且未建清单或存在开放项时拒绝任务完成；
- Todo 模式的模型轮次下限从普通 8 轮提高到 16 轮；
- 成功执行 PowerShell 文件写入命令也可作为文件修改证据，避免模型使用 shell 完成真实写入后仍被完成门误判；
- 新增 `tool_blocked_by_todo_contract`、`todo_completion_blocked` 和 `todo_mode` 诊断字段。

自动化验证共 78 项通过；前端 TypeScript 检查与 Vite 生产构建通过。真实 DeepSeek 先后完成创建、修改、删除三组隔离用例：每组均为 3 项 Todo、4 次 TodoWrite、最终 3/3 完成且无失败工具。随后通过真实 sidecar 全链路重放同形提示，确认 `todo_mode=true`、任务合同为 `mutation`、禁止工具为空、4/4 Todo 完成、文件内容正确且未出现只读拦截。临时目录全部清理。

脱敏证据：`../testing/evidence/todo_mode_crud_20260809_125905.json`、`../testing/evidence/todo_mode_crud_20260809_130035.json`；完整说明见 [`TODO_MODE_REAL_API_TEST_2026-08-09.md`](../testing/TODO_MODE_REAL_API_TEST_2026-08-09.md)。

### 4.25 产物预览、新手引导与 Windows 下载版

本轮把“任务做完了”之后的交付体验补齐，并首次生成不依赖本机 Python 的 Windows 安装包。

产物交付：

- `ChangeSet` 增加工作区根路径，任务结束卡片区分本轮新增/修改产物与完整文件变化；
- 新增文件快捷列表，点击后直接进入内容预览；`.md` / `.markdown` 使用安全 GFM 渲染，其他文本使用纯文本预览，均可切换红绿 unified Diff；
- Rust 新增受根目录约束的资源管理器命令，支持打开产物目录或选中单个文件；规范化后的目标如果逃逸工作区会被拒绝；
- 删除文件不会显示成可打开产物，但仍保留在 Diff 和撤销事务中；预览明确标注为任务结束时的快照。

新手体验：

- 顶栏增加永久可见的“新手指南”，四步覆盖首次填写 Key、项目/纯聊天、模式与权限、模板/Todo/Skill、产物预览/撤销/日志；
- 指南支持步骤跳转、前后翻页、键盘 Escape、遮罩关闭，最后一步可直接进入设置；
- 工具手册继续保留，避免把完整工具字典塞进第一次上手流程。

发布工程：

- 发布配置升级到 `0.8.0`，npm/Cargo 包名和 Tauri identifier 统一为 AstraCode；
- Python sidecar 使用 PyInstaller one-file 冻结，并把 `skills/` 作为资源一起打包；Rust 在 release 模式优先启动安装目录中的 sidecar，开发模式继续使用系统 Python；
- 用户 Key 改为优先写入 `%LOCALAPPDATA%\AstraCode\config.env`，安装包不依赖也不包含项目 `.env`；
- Tauri 生成 Windows x64 NSIS Setup，WebView2 采用下载引导模式；发布目录同时写入 SHA-256；
- 增加 Windows GitHub Actions：推送 `v*` 标签时在干净 runner 构建并附加安装包到 GitHub Release；
- 增加 GitHub 发布指南和 0.8.0 Release Notes。

构建事故与修复：第一次冻结 sidecar 时，开发机全局 Anaconda 同时存在 PyQt5/PySide6，PyInstaller 因多个 Qt binding 拒绝继续。发布脚本改为固定使用 `packaging/build/release-venv` 干净虚拟环境，只安装 `requirements-release.txt`，随后完整构建成功。这个隔离环境是发布可靠性要求，不能为了缩短构建时间改回全局 Python。

验收结果：79 项 Python 自动化测试、前端生产构建、Rust check 与 Rust release 构建通过；冻结 sidecar 的 `hello → get_settings → shutdown` 协议通过；release GUI 能启动打包资源中的 sidecar 并在关闭后回收进程；在空工作目录、空 LocalAppData、清空 API 环境变量的进程中，两个 Key 均报告未配置；sidecar 与安装包扫描未发现 `sk-` 长 Key 特征。浏览器实际点击确认新手指南、Markdown 渲染、Diff 切换、产物目录按钮和单文件预览均可达。安装包位于 `release/AstraCode-Workbench-v0.8.0-Windows-x64-Setup.exe`，大小 18.47 MiB，SHA-256 为 `75c6a8199894ac26a958dc68c1e2819b17477891bd702edddf5efe206f4dd2e1`。

当前发布边界：尚未购买代码签名证书，因此 Windows SmartScreen 可能显示未知发布者；发布前仍应在另一台无开发环境的 Windows 10/11 上做安装、升级与卸载验收。

### 4.26 0.8.1 新手导览、文件卡片与浅色 Markdown 修复

用户截图暴露出三个纯界面问题：旧新手指南左侧使用了没有信息价值的装饰卡片；卡片里的图标颜色依赖未定义的 `--blue`，在白底上变成不可见的白色图标，只剩一个白方块；本轮文件操作按钮过大且割裂；浅色 Markdown 仍复用深色代码块颜色，与文档背景不协调。

本轮调整：

- 删除旧的数字装饰卡，指南从四页扩展到五页；每页都渲染缩小版 AstraCode 工作台，用蓝色高亮框圈出项目区、输入框、任务控制栏、运行概览或本轮文件，再用连线和说明卡解释用途；
- 补齐 `--blue`、`--blue-soft`、`--panel-soft` 和字体变量，解决原白色方块根因；指南支持浅色/深色、窄屏重排和 `prefers-reduced-motion`；
- 所有用户可见文案由“产物”改为“文件”，操作统一为“查看变更 / 打开文件夹 / 撤销”；三个按钮收进同一紧凑操作组，以轻量分隔线和主次颜色融合到文件卡片；
- Markdown 新增独立代码主题变量，浅色代码块使用浅灰蓝表面、深色代码和蓝色左边线，深色主题继续使用深蓝表面；行内代码不再和代码块共用硬编码颜色；
- 浏览器演示 Markdown 增加 Python fenced code block，作为浅色兼容回归样例；
- 版本升级为 `0.8.1`，重新生成 Windows NSIS 下载版。

界面验收：浏览器实际点击确认指南为 5 步，第一步和第五步的高亮框、箭头和说明卡均正确指向目标；文件卡片显示“1 个本轮文件”，紧凑操作组显示“查看变更 / 打开文件夹 / 撤销”；浅色 Markdown 正确渲染 `print("Hello AstraCode")` 代码块，背景、边框和文字对比清晰。

发布验收：79 项 Python 测试、前端生产构建、Rust check 和 Tauri release 构建通过；冻结 sidecar 在空配置目录中报告版本 `0.8.1`、两个 Key 均未配置，并能正常 shutdown；release GUI 成功启动打包内 sidecar；安装包和 sidecar 的 `sk-` 长 Key 特征扫描结果均为 0。新安装包大小 18.47 MiB，SHA-256 为 `925f71f4c604703401580bf0efb3a1e5d64f176f5f2f145e9a2922d2eb650260`。

### 4.27 原版能力完整性审计与 Memory 文档补录

问题：用户复查产品文档时发现 Memory 未出现在功能表。进一步审计确认，原版持久任务板、MessageBus、队友关停/计划审批、后台通知回注和 REPL 管理命令也被压缩在少量概括性表述中，没有形成可追溯的功能清单。

本轮采用源码而非回忆做三路核对：

- `agents/s_full.py`：逐个核对 section、class/function、23 项工具和自动生命周期；
- `agents/s_full_eval.py`：确认它是禁用 Memory 的评测实验分支，并识别其完成前自测与错误恢复提示；
- 当前 `agent_harness/`：核对 27 项 schema、handler、模块实例化、sidecar 的 per-session `state_root` 和桌面能力。

补录结果：

- `PRODUCT_DESIGN.md` 增加完整能力血缘、27 项工具分类、长期 Memory、持久任务板、后台任务、团队消息协议和终端兼容入口；
- 明确当前 Memory 仍会在每轮构建 system prompt 时选择最多 5 条相关记忆，选择模型失败则按关键词降级；任务成功后自动提取耐久信息，记忆达到 10 条后尝试合并去重；
- 明确 Memory、`.tasks`、`.team` 和 `.transcripts` 已从用户项目迁移到 `%LOCALAPPDATA%\s_full\sessions\<session-id>\runtime`，按会话隔离；
- 明确 Todo 是本轮短清单，TaskManager 是带 ID、负责人和依赖的持久任务板；用户 Plan V1 与 Teammate 的 `plan_approval` 是不同机制；
- 明确原版不含 s12 worktree isolation，当前协调器也不等于 worktree 隔离；
- 更新简历文档，在诚实标注开源继承边界的前提下加入 Memory、任务板和团队消息等完整能力。

本轮只修改文档，没有改变运行时代码。验证方式为静态源码路径、类实例化、工具 schema 和文档引用核对；因此没有重复消耗真实 API。发现的后续技术债务是：Memory 没有用户管理 UI，真实 API 套件普遍使用 `finalize_memory=False` 控制成本，目前仅 Fake Client 间接覆盖提取调用，仍需要独立的 Memory 单元测试与受控真实回归。

### 4.28 项目交接文档与文档中心整理

问题：`docs/project_docs/` 顶层累计了产品、架构、测试、发布和求职材料共 20 余份文档。新开发者或 AI 很难先找到项目全貌，同类资料也散落在一起。

本轮调整：

- 新增顶层 `PROJECT_HANDOFF.md`，完整说明项目用途、原版血缘、当前功能、27 项工具、任务流、代码结构、数据位置、已知边界和专题文档入口；
- 保留全部旧文档和测试证据，没有删除历史资料；
- 更新根目录 `README.md`、`AGENTS.md` 和文档内部引用，开发文档的强制维护路径改为 `docs/project_docs/product/`；
- 约定真实模型报告进入 `testing/`、脱敏机器证据继续放在 `testing/evidence/`，避免顶层再次堆积。

本轮没有修改运行时代码，也没有调用真实模型。验证包括目录清单、Markdown 相对链接目标、旧顶层路径残留和关键文档入口检查。

### 4.29 GitHub 公开源码整理

2026-10-11：为公开源码补齐根目录 MIT License（保留 shareAI Lab 版权）、NOTICE、CONTRIBUTING、PRIVACY、SECURITY 和完整 README。修正桌面说明中的过期 Plan/审批状态，真实测试目录从固定本机路径改为系统临时目录或 `S_FULL_TEST_BASE`。新增 `requirements-dev.txt`、离线 CI 和允许列表导出工具 `packaging/export_public.py`。

公开副本保留应用源码、Skill、测试、锁文件、技术文档和历史快照；排除凭据、个人求职资料、运行库、Memory、缓存和构建文件。文档与证据中的个人本机路径仅在导出副本脱敏，原开发资料保留。导出时检查凭据模式、JSON 合法性及 Markdown 相对链接，生成 SHA-256 源码清单和 ZIP。

首次 sandbox 测试为 78 passed / 1 failed，失败在取消命令后临时目录仍被子进程占用。解除本地进程沙箱后单测通过，公开副本 79 项原有测试全部通过；因此没有为测试环境限制修改运行时回收代码。前端生产构建通过。另新增 5 项导出规则/敏感值/链接/脱敏回归；最终结果见公开准备报告。

GitHub 上传脚本使用本机已登录的 Git Credential Manager，只在进程内使用凭据、不回显或落盘，提交前逐项验证清单哈希，并拒绝覆盖已有历史或更改已有私有仓库的可见性。公开版与原开发目录分离。进度与远端状态在根目录 `DEVELOPMENT_STATUS.md` 持续记录。

公开上传时另发现旧 `.gitignore` 中 `release/` 同时忽略了 `docs/project_docs/release/`，造成发布文档无法加入 Git。改为根目录限定的 `/release/`，既排除安装包又保留发布说明。失败时远端仅创建了空仓库，尚未推送提交；修复后重新导出并正常提交。

首次 GitHub CI 另暴露 Windows 临时目录的短长路径差异：83 项通过，`test_optional_state_root_keeps_runtime_metadata_out_of_project` 把 `RUNNER~1` 与规范化的 `runneradmin` 当成不同路径。测试根目录改为 `.resolve()` 后比较，保留原有隔离断言和运行时行为；通过后续提交修复。

## 5. 测试策略

### 自动化

```powershell
python -m unittest discover -s tests
```

覆盖：权限、并发、上下文、完成门、工具协议、工具参数、命名、数据库、sidecar、Plan、取消、工作区以及 Fake Client 下的 Memory 提取调用。

### 桌面构建

```powershell
cd desktop
npm run build
cd src-tauri
cargo check
```

### Windows 下载版

```powershell
.\packaging\build_windows.ps1
```

构建脚本会冻结 sidecar、执行 Tauri production build、复制 NSIS Setup，并生成同名 `.sha256`。发布前额外做无 Key 协议烟雾测试和安装包凭据特征扫描。

### 真实 API CRUD

```powershell
python -m tests.live_deepseek_crud
```

只在 `<TEST_ROOT>\s_full_live_crud_*` 隔离目录运行，finally 校验并清理。

Todo 模式专项测试：

```powershell
python tests\live_forced_todo.py
```

覆盖真实 DeepSeek 创建、修改、删除和桌面 sidecar 参数传递；仅保存脱敏工具名、状态和断言结果。

### 真实标题请求

使用 V4 Flash、thinking disabled、48 Token，无工具。验证输出清洗、长度和无额外 Key。

## 6. 排障手册

### 找到最新运行日志

```text
<USER_HOME>\AppData\Local\s_full\sessions\<session-id>\runs\<request-id>.jsonl
```

调试模式可直接点击“打开日志”。

### 查看会话完整事件

```text
<USER_HOME>\AppData\Local\s_full\sessions\<session-id>\events.jsonl
```

### 查看模型历史

数据库：

```text
<USER_HOME>\AppData\Local\s_full\index.sqlite
```

检查 `model_state.history_json` 时只输出 role、block type、tool ID 和参数字段，避免泄露 thinking 或用户敏感内容。

### 常见事件

- `model_call_started/completed/failed`：模型请求；
- `tool_started/completed`：工具执行；
- `tool_blocked_by_todo_contract/todo_completion_blocked`：Todo 模式的初始化、形状或完成约束拦截；
- `completion_evaluated`：完成门决策；
- `message_protocol_repaired`：工具消息链自愈；
- `title_generation_failed`：命名模型失败，主任务不受影响；
- `diagnostic_error`：含 traceback 的系统错误；
- `task_completed/incomplete/cancelled`：终态。

## 7. 当前技术债务

1. 权限系统不是 OS 沙箱，shell 规则可能漏判。
2. 事务 V1 只覆盖文本文件，不覆盖二进制、数据库、外部服务和所有 Shell 副作用。
3. Verifier 已能检查内容，但仍需长期评测误报、漏报和成本。
4. 上下文 Token 是估算值，不是服务端精确 tokenizer。
5. Plan 步骤没有完全驱动工具级进度。
6. 子 Agent 和 Teammate 缺少完整 UI 与资源预算。
7. Key 保存在 `%LOCALAPPDATA%\AstraCode\config.env`，尚未使用 Windows Credential Manager。
8. Windows 安装包已经可构建，但尚未完成代码签名、自动更新和跨平台包。
9. React 主组件仍较大，后续应拆分日志、对话、侧栏和 composer 组件。
10. Memory 会增加相关性选择、完成后提取和合并的模型调用，目前没有 UI 查看/编辑/禁用，也缺少独立忠实度与成本评测。
11. 持久任务板没有独立桌面视图；Todo 与 TaskManager 的适用边界主要依赖 system prompt。
12. 后台任务状态只存在当前进程内，桌面重启后无法重新附着；Teammate 的线程也不能跨重启继续。
13. 当前通过单协调器串行访问共享工作区，不是 Git worktree 隔离；多 Agent 并行写入吞吐有限。

## 8. 未来 AI 接手检查清单

开始修改前：

- 阅读三份核心产品文档；
- 查看最新运行日志而不是猜测；
- 确认当前桌面进程是否加载了最新 Python；
- 检查用户工作树，不覆盖无关变更；
- 明确是否需要真实 API 测试。

修改完成后：

- 增加与故障同形的回归测试；
- 跑全量 Python 测试；
- UI 变更跑 `npm run build`；
- Rust 变更跑 `cargo check`；
- 模型协议变更至少跑一次隔离真实 API 测试；
- 清理测试目录；
- 重启 Tauri 开发端；
- 更新本文和产品设计状态。
