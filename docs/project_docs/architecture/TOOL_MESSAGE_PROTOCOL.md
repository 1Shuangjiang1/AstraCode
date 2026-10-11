# 工具消息协议与中断恢复

## 问题背景

DeepSeek 的 Anthropic 兼容接口要求：只要一条 assistant 消息包含 `tool_use`，紧随其后的 user 消息就必须包含该轮每一个调用 ID 对应的 `tool_result`。缺少任意一个结果，后续请求都会收到 HTTP 400。

2026-08-08 的故障日志显示，会话在执行 `write_file` 时被中止，历史被保存成：

1. assistant：文本 + `tool_use(call_00_mZtrQ9iOU1OojlH4zkxs7224)`
2. user：下一轮的新任务

中间缺少 `tool_result`，所以新任务在模型生成内容前就被接口拒绝。

## 当前实现

- `agent_harness/message_protocol.py` 集中维护工具消息协议。
- 用户停止任务时，当前工具的真实结果仍会写回；尚未执行的同轮工具会写入明确的“已中断”错误结果。
- 每次调用模型前都会检查消息链。发现旧的孤立 `tool_use` 时，会把合成错误结果放在下一条 user 消息最前面，并保留用户原始文本。
- 保存模型历史前再次修复，防止异常退出、计划模式或未来代码路径把半截消息写入数据库。
- 是否执行工具以回包的实际内容块为准，不再只依赖供应商的 `stop_reason`。
- 修复发生时写入诊断事件 `message_protocol_repaired`，包含修复的调用 ID 和数量。

## 中断语义

合成结果会明确告诉模型：工具在结果落盘前被中断，不得假设它已经读取或修改工作区。这比伪造成功结果安全，也允许模型在下一轮根据用户的新指令决定是否重试。

## 回归覆盖

`tests/test_message_protocol.py` 覆盖：

- 孤立工具调用后直接出现新用户消息；
- 一轮多个工具但只保存了部分结果；
- 合法历史保持不变；
- 数据库存储保护；
- 工具执行过程中取消；
- 非标准 `stop_reason` 携带工具块；
- 旧坏会话在真实模型调用前自动恢复。

## 排障位置

- 每次运行：`%LOCALAPPDATA%\s_full\sessions\<session-id>\runs\<request-id>.jsonl`
- 会话总日志：`%LOCALAPPDATA%\s_full\sessions\<session-id>\events.jsonl`
- 模型历史：`%LOCALAPPDATA%\s_full\index.sqlite` 的 `model_state` 表
- 本次修复前备份：`%LOCALAPPDATA%\s_full\backups\index-before-tool-protocol-repair-20260808-111512.sqlite`
