# AstraCode Workbench 0.8.1

这是 AstraCode 的 Tauri 2 桌面端，由 React 界面、Rust 桥接和冻结的 Python sidecar 组成。

普通用户在 GitHub Releases 下载 `AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe` 安装，无需开发环境。源码包不包含安装包；开发者使用下方命令。

## 启动

首次启动，在项目根目录运行：

```powershell
.\run_desktop.ps1 -Install
```

以后运行：

```powershell
.\run_desktop.ps1
```

窗口关闭时，Rust 层会先通知 Python sidecar 退出；若 sidecar 没有及时响应，则会回收该子进程。

## 当前能做什么

- 使用系统文件夹选择器选择项目。
- 切换 Agent 或 Plan 预览模式。
- 切换安全、需要审批、完全访问三种权限显示。
- 提交 DeepSeek 在线任务并查看会话、状态、工具和完成事件。
- Plan 预览会显示结构化步骤。
- 直接运行 `npm run dev` 时，浏览器会使用内置 demo transport，方便调整界面。
- 输入框下方可快速选择 Agent/Plan、权限以及快速/High/Max 思考强度。
- 任务运行时发送按钮变为“停止任务”；点击后立即取消模型任务并终止活动命令。
- 任务完成后列出本轮文件；Markdown 可直接渲染预览，其他文本可预览内容或红绿 Diff，并能在资源管理器中定位文件或目录。
- 顶栏“新手指南”用五步展示项目、输入区、权限与模式、进度和文件预览。

Tauri 模式连接 AgentApp 和 DeepSeek，浏览器预览使用离线模拟。桌面审批 broker 与 Plan V1 已实现：高风险工具可在桌面确认，Plan 支持批准、修改和取消。步骤级自动重新规划仍待后续版本。

## 目录

```text
desktop/
├─ src/                  # React UI 和 transport
├─ src-tauri/
│  ├─ src/main.rs        # Python 进程生命周期与 JSONL 转发
│  ├─ capabilities/      # 最小 Tauri 能力白名单
│  └─ icons/             # 桌面应用图标
├─ app-icon.svg          # 图标源文件
├─ package.json
└─ vite.config.ts
```

Python 端入口是：

```powershell
python -u -m agent_harness.sidecar
```

协议与后续开发计划见 [路线图](../docs/project_docs/product/DEVELOPMENT_ROADMAP.md)，完整安装配置见 [根目录 README](../README.md)。

## 验证命令

```powershell
npm run build
cd src-tauri
cargo check
```
