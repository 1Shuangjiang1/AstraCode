# 参与开发

从 README 的源码运行步骤配置环境。修改前阅读 `AGENTS.md`、`docs/project_docs/PROJECT_HANDOFF.md` 和对应专题文档。

- 不修改 `upstream/`、`legacy/` 历史快照。
- 新工具应同时提供 schema、handler、风险判断与回归用例。
- 主/子/队友统一使用 ToolExecutor；项目文件访问通过 WorkspaceTools 和协调器。
- 修改消息协议时保证 tool_use/tool_result 成对；检查取消、失败和恢复路径。
- 开发改动同步更新产品设计及产品开发文档。
- 不提交 `.env`、密钥、真实会话数据库、个人 Memory 或原始私有日志。

提交前运行 `python -m pytest -q`，UI 改动运行 `npm run build`，Rust 改动运行 `cargo check`。真实模型测试是手动选择，会产生费用，不由 CI 自动调用。

Issue 请说明版本、平台、最小复现、期望和实际结果。PR 请解释解决的问题、行为变化和验证结果。对于公开源码导出工具，可以运行 `python packaging/export_public.py` 并检查生成的清单。
