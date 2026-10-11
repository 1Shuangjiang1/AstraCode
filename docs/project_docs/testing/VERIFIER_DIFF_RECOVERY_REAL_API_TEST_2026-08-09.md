# Verifier、Diff/撤销与恢复真实 API 测试报告

日期：2026-08-09  
版本：AstraCode Workbench 0.7.0

## 结论

最终验收通过。主 Agent 和严格 Verifier 均实际调用 DeepSeek；文件检查与撤销在 `<TEST_ROOT>` 隔离临时目录完成，测试后业务目录与运行状态目录都已删除。

## 覆盖范围

| 场景 | 结果 | 客观证据 |
| --- | --- | --- |
| 创建中文 Python 函数教程 | 通过 | `write_file`、`read_file` 均成功，Agent 状态 completed |
| 严格独立验证 | 通过 | Verifier 用只读工具读取文件，3 轮后判定 pass |
| 修改清单与 Diff | 通过 | 1 个新增文件，+21/-0，manifest 已生成 |
| 一键撤销核心 | 通过 | 状态 rolled_back，新增文件不存在 |
| 重启后恢复 | 通过 | 未完成 run 被识别为 interrupted，保留 pending `write_file` 检查点 |
| 既有真实 CRUD 回归 | 通过 | 创建、修改、删除三轮通过；10 次模型调用，0 请求失败 |

## 失败样本的处理

前两次新用例未通过，证据文件也保留在 `testing/evidence`：

1. 测试运行数据错误地放进工作区，使事务捕获到自身文件；已将状态目录移到工作区外。
2. 宽泛提示下模型未创建目标文件；严格 Verifier 正确判为 `needs_fix`。将用例改为与真实 CRUD 一致的明确工具任务后通过。

这说明 Verifier 会拒绝“模型口头说完成但交付物不存在”的结果，符合设计目标。

## 自动化结果

- `python -m pytest -q`：73 passed；Windows 取消命令句柄用例连续 8 次通过。
- `npm run build`：通过。
- `cargo check`：通过。
- 最终脱敏 JSON：`evidence/verifier_changes_recovery_20260809_025730.json`。

证据不包含 API Key、请求头或隐藏思维链。
