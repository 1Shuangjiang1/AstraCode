# 来源与第三方组件

AstraCode 基于 [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的 `s_full.py` 及其配套 Skill 演进，上游采用 MIT License，版权属于 shareAI Lab。原始许可证保留在 `upstream/LICENSE`，根目录许可证保留同样的版权和许可条款。

原版已包含 Agent 循环、Todo、任务板、Skill、Memory、上下文压缩、后台任务和多 Agent 协作。本项目对其进行模块化及桌面化，并增加统一权限、SQLite 会话、诊断、验证、恢复和文件变更管理。`upstream/` 为原版对照，`legacy/` 为重构前快照，当前运行入口为 `agent_harness/` 与 `desktop/`。

Python 使用 Anthropic SDK、python-dotenv 等组件；桌面使用 Tauri、React、Vite、lucide-react、react-markdown、remark-gfm 等组件；安装包使用 PyInstaller。第三方组件的许可证以各自安装包/上游声明为准，根目录 MIT 许可证不替代它们。npm 与 Cargo 锁文件保留依赖版本和来源。

项目是独立学习和开发项目，不代表 Anthropic、DeepSeek、Tauri 或其他依赖作者的官方产品。
