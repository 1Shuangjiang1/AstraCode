# DeepSeek 真实 API CRUD 回归记录（2026-08-08）

## 故障

失败请求返回 `stop_reason=max_tokens`，并用满旧配置的 8000 个输出 token。回包包含 `write_file` 工具名，但参数为 `{}`，旧执行器直接调用处理函数，产生缺少 `path` 和 `content` 的 Python 异常。

## 修复

- 主 Agent 输出上限改为可配置的 `S_FULL_MAX_OUTPUT_TOKENS`，默认 32768。
- 真实环境 API 超时由 120 秒调整为 300 秒。
- 所有工具执行前统一校验必填字段、字段类型、空字符串和意外字段。
- 截断回包携带不完整工具调用时，返回可恢复的 `tool_result`，提示模型用完整参数简洁重试。
- 子 Agent、Teammate 和 Plan 模式复用新的输出预算与工具块判断逻辑。

DeepSeek 官方当前标注 V4 Flash 最大输出为 384K，Anthropic 兼容接口完整支持 `max_tokens`、工具 schema、思考开关和 `output_config.effort`：

- <https://api-docs.deepseek.com/quick_start/pricing>
- <https://api-docs.deepseek.com/guides/anthropic_api>

## 真实 API 测试

配置：`deepseek-v4-flash`、思考开启、effort=high、真实 API、完全访问权限、隔离目录位于 `<TEST_ROOT>`。

同一个多轮会话依次执行：

1. 创建 `python_code_tutorial.md`，内容包含变量、函数、类、异常、文件 IO 和可运行示例，并读取验证。
2. 修改标题，增加 pytest 练习小节，并读取验证。
3. 删除文件，使用 `path_exists` 确认不存在。

结果：

| 步骤 | 状态 | 文件断言 | 耗时 |
| --- | --- | --- | --- |
| 创建 | completed | 通过 | 8.63 秒 |
| 修改 | completed | 通过 | 6.10 秒 |
| 删除 | completed | 通过 | 2.83 秒 |

- 真实模型调用：9 次
- 模型调用失败：0 次
- 非法工具结果：0 次
- 测试目录残留：0

## 自动化回归

全量 59 项测试通过。新增覆盖：

- `write_file` 缺少 `path/content` 时不会调用处理器；
- 非法额外字段被拒绝；
- `max_tokens + 空工具参数` 会在下一轮正确重试；
- 工具调用/结果链在取消与持久化后仍保持合法。

可重复运行真实测试：

```powershell
python -m tests.live_deepseek_crud
```

脚本只允许清理 `<TEST_ROOT>\s_full_live_crud_*` 格式的隔离目录。
