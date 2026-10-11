# s_full 真实 DeepSeek 全功能测试报告

> 测试日期：2026-08-08；最终结果：10 / 10 通过。

## 1. 测试目标

验证当前 coding agent 的核心链路不是“单元测试能过”，而是在真实模型、真实工具循环和真实 Windows 文件系统下能够完成任务。所有写入均位于 `<TEST_ROOT>\s_full_live_full_*` 隔离目录，套件结束后自动清理。

## 2. 环境与方法

- 主模型：`deepseek-v4-flash`，真实 DeepSeek API，高思考模式。
- 自动命名：硅基流动 `deepseek-ai/DeepSeek-V4-Flash`，真实 API。
- 权限：功能案例使用 `full_access`，但 critical 操作保持硬拦截；权限边界另做确定性验证。
- 平台：Windows / PowerShell / Tauri 2 + Python sidecar 项目。
- 测试脚本：`tests/live_deepseek_full_suite.py`。
- 最终原始证据：`testing/evidence/full_suite_20260808_155745.json`。

原始证据不保存 API Key、Authorization 请求头或完整模型思维内容。

## 3. 最终结果

| 案例 | 结果 | 耗时 | 可追踪主/Plan 模型调用 | 核心验证 |
| --- | --- | ---: | ---: | --- |
| 文件 CRUD、Todo、命令 | 通过 | 11.53s | 6 | 两个代码文件、4 次成功 Todo 更新、真实 Python 验证 |
| 持久任务与 Skill | 通过 | 8.11s | 6 | 创建/列表/更新/读取任务；加载内置 code-review |
| 单个 Explore 子 Agent | 通过 | 49.42s | 5 + 1 个子 Agent | 子 Agent 只读审查，主 Agent 写报告并验证 |
| 两个 Explore 子 Agent | 通过 | 139.87s | 5 + 2 个子 Agent | 两路独立审查后合并报告 |
| 后台任务 | 通过 | 9.78s | 8 | background_run、4 次状态检查、结果文件验证 |
| 两个 teammate | 通过 | 16.06s | 9 + 2 个 teammate | 两个线程分别写文件；共享工作区串行写入 |
| Plan 只读后批准执行 | 通过 | 65.97s | 12 | Plan 阶段零写入；执行后代码、测试和命令验证完成 |
| 聊天模式目录选择 | 通过 | 4.96s | 4 | 先选绝对目录，再写入和读取 |
| 三档权限边界 | 通过 | <0.01s | 0 | safe 拒绝写；approval 高风险询问；critical 硬拦截 |
| 自动命名 | 通过 | 1.56s | 独立命名调用 | 返回“测试Todo与子Agent功能” |

总计：

- 10 个案例全部通过；
- 51 次可追踪的主 Agent / Plan 模型调用；
- 额外执行 3 个真实子 Agent 和 2 个真实 teammate 的模型循环；
- 0 次主/Plan API 调用失败；
- 0 次 tool_use / tool_result 协议修复；
- 临时目录清理成功。

出现过 1 次可恢复的 Todo 校验失败：模型一次提交了不符合约束的 Todo 状态，本地校验器拒绝后，模型在同一任务中自行修正，最终案例通过。这证明参数护栏和自恢复路径正常。

## 4. 测试中发现并修复的问题

### 4.1 完成合同把“持久任务”误认为文件修改

旧规则看到“创建”后，会跨越逗号继续匹配后面的“计算模块”，错误要求 `write_file/edit_file/delete_file` 证据。Agent 已完成任务管理工具，却被完成门强制继续。

修复：中文文件意图只在同一分句内匹配，并禁止穿过“任务、计划、清单”等非文件对象。

### 4.2 子 Agent 的只读要求污染主 Agent

“让子 Agent 只读审查，然后主 Agent 写报告”曾被全局解释为整个任务只读，导致主 Agent 的合法写入被拦截。

修复：只有“全程只读、本次任务只读、项目只读、只读模式”等全局表达才触发全局限制；角色局部要求不再扩散。

### 4.3 Shell 可以绕过只读合同

专用写入工具被任务合同拦截时，模型可能改用 `Set-Content` 等 PowerShell 命令实现同一写入。

修复：只读合同同时识别并拦截 Shell 中的写入、复制、移动、重命名、删除和重定向操作。

### 4.4 teammate 写入缺少可观察完成证据

主 Agent 被要求不得亲自写文件时，teammate 已完成写入，但完成门只认可主 Agent 的直接 mutation 工具，导致持续运行。

修复：对于明确委派的写入任务，`delegation + 后续文件检查` 可组成完成证据；仍要求主 Agent 实际检查结果，不能仅凭“已启动 teammate”结束。

### 4.5 Plan 批准后仍受计划阶段只读文字影响

执行提示携带原始“计划阶段不要修改文件”请求，批准执行后完成门仍阻止写入。

修复：执行合同去除原始 planning-only request，只传递结构化步骤，并明确只读阶段已经结束。

### 4.6 外部项目无法加载内置 Skill

旧实现只搜索当前工作目录下的 `skills/`。用户选择外部项目后，应用自带 `code-review` 等 Skill 变成 Unknown skill。

修复：先加载应用内置 Skill，再加载项目本地 Skill；同名时项目版本覆盖内置版本。

## 5. 三轮真实测试变化

| 轮次 | 结果 | 说明 |
| --- | --- | --- |
| 第一轮 | 5 / 10 | 暴露完成合同、Plan 执行和 Skill 搜索问题；87 次主/Plan 调用 |
| 第二轮 | 9 / 10 | 子 Agent、teammate、Plan 修复生效；剩余内置 Skill 与任务语义问题 |
| 最终轮 | 10 / 10 | 所有案例通过；51 次主/Plan 调用，0 API 失败 |

从 87 次降到 51 次，说明修复不仅让状态变绿，也消除了大量无意义的补救轮次和额外费用。

## 6. 自动化回归

- Python：66 项测试全部通过。
- TypeScript/Vite 生产构建：通过。
- Rust/Tauri `cargo check`：通过。
- 测试临时目录：全部清理，无 `s_full_live_*` 残留。

## 7. 尚未覆盖或仍需加强

- 本轮验证了 UI 所依赖的 sidecar 协议和生产构建，但没有自动点击桌面 UI 的每个弹窗。
- 审批模式验证了引擎决策边界，没有让真人逐次点击真实审批弹窗。
- 51 次统计不包括子 Agent / teammate 内部请求；后续应把子角色调用也接入统一 trace。
- 高思考子 Agent 的真实耗时受服务负载影响，多子 Agent 案例约 140 秒；未来可为 Explore 单独配置更快模型或输出预算。
- 当前多个子 Agent 在父 Agent 内同步执行；功能正确，但不是真正并行。若要提速，需要新增并行委派调度和结果汇合协议。

## 8. 复跑方式

在项目根目录执行：

```powershell
python tests/live_deepseek_full_suite.py
```

脚本只允许清理名称以 `s_full_live_full_` 开头、且解析后位于 `<TEST_ROOT>` 内的测试目录。

