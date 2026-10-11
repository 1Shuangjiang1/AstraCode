[English](README.md) | [简体中文](README.zh-CN.md)

# AstraCode Workbench

**通过自然语言操作本地项目的桌面 Coding Agent。**

AstraCode 将文件读写、命令执行、计划、Todo、子 Agent 和多 Agent 协作放进一个桌面工作台。你可以让它编写代码、整理文档、运行测试，也可以先审阅计划，再允许实施。执行过程、文件变化和日志可以直接查看。

当前版本 **0.8.1**，主要支持 **Windows 10/11 x64**。项目基于 [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的 `s_full.py` 演进，保留上游机制并完成模块化、桌面化和可靠性增强。原版与新增功能的对应关系见 [产品设计](docs/project_docs/product/PRODUCT_DESIGN.md)。

## 下载安装：普通用户

在本仓库的 **Releases** 页面寻找：

```text
AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe
AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe.sha256
```

选择 `Setup.exe` 安装；GitHub 的 Source code 压缩包是给开发者的。如果还没有 Release，请使用下方源码运行方式。

1. 运行安装包，完成安装并打开 AstraCode。
2. 在右上角“设置”填写自己的 DeepSeek API Key。
3. 点击侧栏 `+` 添加项目文件夹，在项目旁点击 `+` 新建对话。
4. 输入任务并发送。首次建议保持“需要审批”。
5. 打开右上角“新手指南”和“工具手册”了解按钮及工具用法。

安装包包含 Python 后端，无需安装 Python、Node.js 或 Rust。Agent 执行你的项目命令时，该项目依赖的 Python、Git、编译器等仍需安装。首次安装可能联网获取 WebView2。当前安装包尚未商业签名，Windows 可能显示未知发布者提示。

## 从源码运行：开发者

### 环境

| 环境 | 用途 |
| --- | --- |
| Windows 10/11 x64 | 当前桌面和命令执行的主要平台 |
| Python 3.10+，建议 3.12 | Agent 后端 |
| Node.js 22.12+ 或 24 LTS、npm | React/Vite 前端 |
| Rust stable、Cargo | Tauri 桌面程序 |
| Visual Studio C++ Build Tools、Windows SDK | Windows 编译依赖 |
| WebView2 Runtime | 桌面 WebView |

下载或克隆仓库后，在**仓库根目录**执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 让桌面端使用正确的 Python 环境
$env:S_FULL_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path

# 复制后编辑 .env，填入自己的 Key
Copy-Item .env.example .env

# 首次安装前端依赖并启动
.\run_desktop.ps1 -Install
```

后续同一窗口运行 `.\run_desktop.ps1`。新窗口需要重新设置 `S_FULL_PYTHON`，或激活 `.venv`。也可以配置好开发环境后双击 `双击启动桌面端.bat`，它使用 PATH 中的 Python。

若 PowerShell 拒绝脚本，可只对当前窗口设置：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

源码不包含冻结 sidecar；开发模式启动 Python 模块，发布构建才生成 sidecar 并打包。

### 终端和离线入口

```powershell
.\.venv\Scripts\Activate.ps1
.\run.ps1 -PermissionMode approval

# 不调用真实模型
.\run.ps1 -Offline
```

Fake Client 用于检查工具循环和协议，默认返回模拟答复，不具备真实模型的代码生成能力。

### 浏览器预览

```powershell
cd desktop
npm ci
npm run dev
```

浏览器访问终端提供的地址即可。浏览器使用 demo transport；真实工具、审批和文件操作需要 Tauri 桌面端。

## 使用方法

**项目模式**：添加目录，在项目下建立多条对话，例如“登录功能”“测试修复”“文档整理”。对话默认在该目录工作。

**纯聊天模式**：初始没有工作目录，适合问答与临时任务。涉及文件时先选择目录，审批模式下可能需要确认。

| 输入区控件 | 用法 |
| --- | --- |
| Agent / Plan | Agent 直接执行；Plan 先只读调查并生成计划，等用户批准后实施 |
| 权限 | 安全、需要审批、完全访问 |
| 快速 / High / Max | 控制是否思考和思考强度，取决于 Provider 支持 |
| Todo | 强制先拆出 3–7 步，执行并更新清单 |
| 验证 | 关闭、标准、严格；严格档可只读复查和触发一次定向修复 |
| 模板 | 选择后在大编辑器补齐要求，再确认填入 |
| `/` | 搜索和加载项目或内置 Skill |
| 发送 / 停止 | 运行中再次点击，取消模型请求及活动命令 |

可以尝试：

```text
在当前项目创建一个 Python 字符串解码函数，支持嵌套括号。
写入 decode_string.py，添加测试并运行，最后告诉我结果和文件位置。
```

```text
先只读调查项目入口、依赖和测试结构，提出重构计划。
在我批准前不要修改文件。
```

```text
使用 Todo 拆分任务：整理 README、检查运行命令、补充使用示例。
完成每一步后更新 Todo，并检查修改后的文档。
```

```text
用一个 Explore 子 Agent 查找权限检查入口，主 Agent 阅读测试。
汇总结果，说明是否有绕过权限的工具路径；本次只读。
```

执行记录可展开或收起。Todo 和 Agent 监视器显示进度，文件卡片显示增删改及行数，支持 Markdown/文本预览、红绿 Diff、打开文件夹和撤销。开启调试模式后，任务末尾出现“打开日志”。

## 完整功能

| 模块 | 能力 |
| --- | --- |
| 工作台 | 多项目、多会话、自动标题、置顶/归档/恢复/删除、Markdown、主题、可调侧栏 |
| Agent 工具循环 | 27 项工具、参数校验、权限检查、结果回传、取消和预算 |
| Plan 与 Todo | 可审阅计划、本轮步骤清单、强制 Todo 和实时进度 |
| 持久任务板 | 负责人、状态、依赖、阻塞和领取 |
| 子 Agent | Explore 只读探索与 general-purpose 委派 |
| Teammate | 会话内持续协作、消息总线、广播、任务领取、空闲和关停 |
| 后台任务 | 后台命令、查询和完成通知 |
| Skill | `skills/**/SKILL.md`、内置与项目加载、`/` 菜单 |
| Memory | user / feedback / project / reference 记忆选择、提取、索引与合并 |
| 上下文 | 旧工具结果裁剪、原文外置、结构化摘要和近期窗口 |
| 可靠性 | 工具消息配对修复、完成证据检查、可选独立验证和中断检查点 |
| 修改管理 | 文本快照、Diff、预览、冲突保护撤销和失败回滚 |
| 诊断 | JSONL、调试按钮、工具时间线和多 Agent 监视器 |
| 测试和发布 | Fake Client、离线测试、真实 API 套件及 Windows 安装包 |

Todo、Memory、Skill、任务板、多 Agent 基础机制来自原版。当前重点增强模块化、桌面交互、统一权限、持久化和运行可靠性，详见能力血缘表。

## 模型配置

当前主模型配置使用 Anthropic Python SDK 和 DeepSeek 兼容接口：

```dotenv
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=填写你自己的Key
S_FULL_MODEL=deepseek-v4-flash
S_FULL_THINKING=1
S_FULL_REASONING_EFFORT=high
```

代码将关闭思考映射为 `thinking.type=disabled`，开启时使用 `thinking.type=enabled` 与 `output_config.effort=high/max`。更换模型时应核对接口兼容性；并非所有模型支持这些参数。参考 [DeepSeek Anthropic 兼容说明](https://api-docs.deepseek.com/guides/anthropic_api)。

自动标题是独立的可选配置：

```dotenv
S_FULL_TITLE_BASE_URL=https://api.siliconflow.cn/v1
S_FULL_TITLE_MODEL=deepseek-ai/DeepSeek-V4-Flash
S_FULL_TITLE_API_KEY=填写你自己的硅基流动Key
```

未配置或请求失败会回退为首条消息截取，不阻塞主任务。两个 Provider 的 Key 不能混用。

| 常用变量 | 说明 |
| --- | --- |
| `S_FULL_PERMISSION_MODE` | 默认 `approval`；另有 `safe`、`full_access` |
| `S_FULL_COMMAND_TIMEOUT` | 单条命令超时，默认 30 秒，不是固定等待 |
| `S_FULL_MAX_ROUNDS` | 默认 8；部分模式会提高有效下限 |
| `S_FULL_MAX_SECONDS` | 默认 300 秒运行预算 |
| `S_FULL_TOKEN_THRESHOLD` | 近似 100,000 token 后自动摘要 |
| `S_FULL_FAKE_CLIENT` | `1` 使用离线模型模拟 |
| `S_FULL_PYTHON` | 桌面开发模式 Python 路径 |
| `S_FULL_DATA_DIR` | 会话数据根目录 |

配置优先级为进程环境变量、用户 `config.env`、工作目录 `.env`、应用根目录 `.env`。改了文件不生效时，先检查是否有更高优先级配置。

## 数据与权限

Windows 默认数据位置：

```text
%LOCALAPPDATA%\AstraCode\config.env                          配置和 Key
%LOCALAPPDATA%\s_full\index.sqlite                         项目、会话、消息、Plan 和状态
%LOCALAPPDATA%\s_full\sessions\<session-id>\events.jsonl     会话事件
%LOCALAPPDATA%\s_full\sessions\<session-id>\runs\<id>.jsonl  单次运行日志
%LOCALAPPDATA%\s_full\sessions\<session-id>\runtime\         Memory、任务和团队状态
```

`s_full` 是保留的历史数据目录名。CLI 默认会在工作目录保存部分状态，可用 `S_FULL_STATE_DIR` 指定独立目录。数据不会自动同步到 GitHub；请求模型时会把相关消息、文件片段及工具结果发送给配置的 Provider，见 [PRIVACY.md](PRIVACY.md)。

| 权限模式 | 行为 |
| --- | --- |
| safe | 只读/低风险允许，修改和删除等拒绝 |
| approval | 低/中风险通常允许，高风险询问，关键危险操作拦截 |
| full_access | 工作区内无需逐次确认，保留路径边界和关键拦截 |

审批可拒绝、允许一次或允许本会话同类操作。应用权限属于软件层控制，尚非操作系统沙箱。

共享工作区使用串行锁：多个 Agent 可同时思考，文件和命令访问会排队。尚未实现独立 Git worktree；后台进程/队友线程不能跨重启重新附着；摘要可能损失细节；Memory 暂无管理 UI；Verifier 不能替代确定性测试；撤销主要覆盖文本，不覆盖数据库和外部副作用。详见 [项目交接](docs/project_docs/PROJECT_HANDOFF.md)。

## 测试与构建

### 离线测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
cd desktop
npm ci
npm run build
cd src-tauri
cargo check
```

pytest 自动隔离会话数据库；不需要真实 Key。历史真实模型结果位于 [testing](docs/project_docs/testing/)，报告是特定日期的验收记录，不是所有环境下的保证。

### 手动真实模型测试（会产生费用）

填写 `.env` 后，在仓库根目录运行：

```powershell
python -m tests.live_deepseek_crud
python -m tests.live_deepseek_full_suite
python -m tests.live_forced_todo
python -m tests.live_verifier_changes_recovery
```

`live_` 脚本不属于默认 pytest 发现范围。它们真实调用模型、创建修改删除文件和执行命令；默认工作区在系统临时目录中创建并清理。可用 `S_FULL_TEST_BASE` 指定已存在的测试根目录。新证据公开前应脱敏。

### Windows 下载版构建

```powershell
cd desktop
npm ci
cd ..
.\packaging\build_windows.ps1
```

输出到 `release/`。构建使用独立打包环境和 PyInstaller sidecar；GitHub Actions 支持手动构建，推送 `v*` 标签会生成 Release 附件。见 [发布指南](docs/project_docs/release/GITHUB_RELEASE_GUIDE.md)。

## 结构与文档

```text
agent_harness/         Agent、工具、权限、上下文、Memory、协作和持久化
desktop/               React UI 和 Tauri/Rust 桥
tests/                 离线和真实模型套件
skills/                内置 Skill 及脚本
docs/project_docs/     产品、架构、测试、发布资料
packaging/             安装包构建和公开源码导出
upstream/、legacy/     原版和重构前快照
.github/workflows/     CI 和 Windows 发布
s_full.py              CLI 入口及兼容层
```

推荐阅读：[项目交接](docs/project_docs/PROJECT_HANDOFF.md) → [产品设计](docs/project_docs/product/PRODUCT_DESIGN.md) → [产品开发](docs/project_docs/product/PRODUCT_DEVELOPMENT.md) → [专题文档索引](docs/project_docs/README.md)。

公开源码包保留应用、测试、Skill、技术文档和历史源码。个人求职材料、个人 Memory、运行数据库、Key、缓存与编译产物不随源码发布，安装包单独通过 Releases 分发。

## 常见问题

**双击没有窗口？** 源码启动需要完整开发环境。先在 PowerShell 执行 `run_desktop.ps1 -Install` 查看错误；只使用应用请选择安装包。

**浏览器只有模拟数据？** `npm run dev` 只预览 UI，通过 Tauri 才能连接真实 Agent。

**操作为何没审批？** approval 对低/中风险通常自动放行，高风险才询问。只读任务可以选 safe 并明确要求只读。

**命令为什么超时？** 命令在非交互 PowerShell 执行，标准输入为 EOF；不能等待终端人工输入。查看日志中的实际命令、退出码和耗时。

**如何反馈？** 开启调试模式，提供复现步骤、版本和脱敏日志片段。不要上传 Key、个人工作区或未经检查的完整日志。

## 来源与许可证

使用 [MIT License](LICENSE)，保留上游 `shareAI Lab` 版权。对照源码在 `upstream/`，重构前快照在 `legacy/`。依赖适用各自许可证；来源见 [NOTICE.md](NOTICE.md)。开发约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)。
