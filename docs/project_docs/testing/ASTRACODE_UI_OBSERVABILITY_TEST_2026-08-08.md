# AstraCode UI、Skill 与可观测性验收报告

> 测试日期：2026-08-08；结论：通过。

## 测试范围

本轮验收覆盖：

- AstraCode 蓝白品牌与浅色界面；
- 左侧项目栏收起、展开、动画和拖拽宽度；
- 对话标题单行渐隐和悬停全文；
- Prompt 模板选择并填入输入框；
- sidecar Skill 清单与输入 `/` 的命令菜单；
- TodoWrite 实时进度展示；
- 单个和多个子 Agent/Teammate 的生命周期事件；
- Agent 工作监视器；
- Todo/Agent UI 状态持久化；
- 原有 Agent、Plan、权限、后台任务和文件工具回归。

## 结果汇总

| 层级 | 结果 | 说明 |
| --- | --- | --- |
| Python 定向测试 | 16/16 通过 | session store、权限复用、sidecar、Skill 清单和 Agent 事件 |
| Python 完整回归 | 66/66 通过 | 权限、上下文、协议、Plan、取消、工具、并发和数据库 |
| React/TypeScript 生产构建 | 通过 | `tsc` 两套配置与 Vite 构建成功 |
| Rust/Tauri | 通过 | `cargo check` 成功 |
| 浏览器实际点击 | 10/10 通过 | 真实 DOM、动画结束态、拖拽和菜单交互 |
| 真实 DeepSeek 全功能 | 10/10 通过 | 44 次主/Plan 模型调用，0 API 失败，0 工具失败 |

## UI 实际点击断言

使用 Microsoft Edge 的实际 Chromium 运行时加载开发界面，而不是静态分析源码。以下断言全部为 `true`：

1. 顶栏显示 AstraCode；
2. 项目栏可从 200px 以上平滑收起到 80px 以下；
3. 展开后拖动把项目栏加宽 40px 以上；
4. 对话标题计算样式为 `white-space: nowrap`，存在渐变 mask 和完整 `title`；
5. 点击“实现代码功能”模板后，输入框出现验收标准结构；
6. 输入 `/` 后出现 Skill 菜单；
7. 选择 `/code-review` 后出现已选择 Skill 标签；
8. 离线事件链执行后，Todo 区出现当前任务；
9. Agent 协作区出现 Explore；
10. 打开监视器后能看到 Agent 工具完成记录。

视觉证据：`testing/evidence/astracode_agent_monitor_20260808.png`。

## 真实 DeepSeek 回归

证据文件：`testing/evidence/full_suite_20260808_164734.json`。

通过用例：

- `crud_todo_and_command`；
- `persistent_tasks_and_skill`；
- `single_explore_subagent`；
- `multiple_explore_subagents`；
- `background_task`；
- `multiple_teammates`；
- `plan_readonly_then_execute`；
- `chat_mode_directory_selection`；
- `permission_boundaries`；
- `automatic_naming`。

真实运行合计：

- 主 Agent/Plan 模型调用 44 次；
- 模型失败 0；
- 工具失败 0；
- 协议修复 0；
- `TodoWrite` 4 次、`load_skill` 1 次、子 Agent `task` 3 次、Teammate 2 个、后台任务 1 个；
- 测试套件隔离目录自动清理成功。

## 事件和隐私验证

子 Agent/Teammate 现在发出：开始、状态/轮次、可见文本摘要、工具开始、工具结果、完成和失败事件。UI 可按 Agent 切换查看，最多保留每个 Agent 最近 80 条界面事件。

监视器不显示隐藏思维链，只显示模型公开文本、任务、轮次、工具名、结果短摘要和终态。子 Agent 与 Teammate 仍复用主权限引擎和工作区协调锁。

## 测试过程中的环境问题

Computer Use 插件当前安装版本没有暴露其文档所声明的 `sky.documentation()`，窗口操作返回运行上下文错误。该问题属于测试插件环境，不属于 AstraCode。最终改用随工作区提供的 Playwright 和本机 Edge 完成实际 DOM 点击验收。

第一次运行真实套件时，外层命令超时但子进程未停止，短暂产生了重复测试。发现后立即停止较早进程并删除其精确隔离目录；保留的正式套件正常结束且自行清理。没有删除用户目录或项目文件。

## 尚未覆盖的边界

- 尚未在安装包版本做 DPI、多显示器与屏幕阅读器的人工验收；
- 多 Agent 监视器已用真实模型验证后端调用、用自动事件验证 UI，多成员同时频繁刷新仍建议做长时间压力测试；
- 当前 UI 事件只保留摘要，完整审计仍以每次运行 JSONL 为准；
- Skill 菜单支持加载现有 Skill，尚未实现 Skill 参数表单与用户自定义排序。
