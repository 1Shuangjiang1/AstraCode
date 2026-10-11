# AstraCode Workbench 0.8.0

首个可安装的 Windows 预览版。

## 主要功能

- 项目模式与纯聊天模式，多项目、多对话、置顶、归档和删除；
- DeepSeek V4 Flash、三档思考强度、三档权限；
- Agent / Plan、Todo 强制执行、Prompt 模板与 Skill `/` 菜单；
- 子 Agent、Teammate、后台任务和实时进度监视；
- 上下文压缩、运行日志、安全继续和任务取消；
- 独立 Verifier、文件 Diff、一键撤销和失败回滚；
- 本轮产物列表、Markdown 应用内预览和资源管理器入口；
- 顶栏三分钟新手指南及工具手册。

## 安装与首次使用

运行 `AstraCode-Workbench-v0.8.0-Windows-x64-Setup.exe`。首次打开后点击“新手指南”，再进入设置填写自己的 DeepSeek API Key。安装包不包含开发者凭据，使用者无需安装 Python。

## 已知边界

- 当前发布版仅构建 Windows x64；
- 安装包尚未进行商业代码签名，Windows 可能显示未知发布者提示；
- 文件事务主要覆盖文本文件，二进制文件和外部服务副作用不能一键撤销；
- Key 当前保存在用户本地配置文件，后续计划迁移到 Windows Credential Manager。
