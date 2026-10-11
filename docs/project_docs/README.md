# AstraCode 项目文档中心

> 统一入口；更新时间：2026-10-11。

本目录按用途归档项目文档。第一次接手项目时，先阅读 [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)，再按任务进入对应分类。

## 最短阅读顺序

1. [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)：项目用途、完整能力、代码结构、边界和详细资料导航。
2. [`product/PRODUCT_DESIGN.md`](product/PRODUCT_DESIGN.md)：产品目标、完整功能血缘、状态与路线图。
3. [`product/PRODUCT_DEVELOPMENT.md`](product/PRODUCT_DEVELOPMENT.md)：开发历史、故障、修复、测试和接手事项。

## 目录结构

```text
project_docs/
├─ README.md                 # 本索引
├─ PROJECT_HANDOFF.md        # 给开发者或 AI 的完整项目交接
├─ product/                  # 产品设计、开发档案和路线图
├─ architecture/             # 运行机制与专题设计
├─ testing/                  # 测试报告及脱敏原始证据
│  └─ evidence/
├─ release/                  # 版本说明和公开发布指南
```

## product：产品与开发历史

| 文档 | 内容 |
| --- | --- |
| [`PRODUCT_DESIGN.md`](product/PRODUCT_DESIGN.md) | 产品定位、完整功能血缘、27 项工具、当前状态与边界 |
| [`PRODUCT_DEVELOPMENT.md`](product/PRODUCT_DEVELOPMENT.md) | 原版审计、开发记录、事故、修复、测试和技术债 |
| [`DEVELOPMENT_ROADMAP.md`](product/DEVELOPMENT_ROADMAP.md) | 后续开发路线和未完成事项 |

## architecture：核心机制

| 文档 | 内容 |
| --- | --- |
| [`PERMISSION_BOUNDARIES.md`](architecture/PERMISSION_BOUNDARIES.md) | safe / approval / full_access 的真实边界 |
| [`PLAN_MODE_V1.md`](architecture/PLAN_MODE_V1.md) | Plan V1 设计与状态机 |
| [`CONTEXT_MODULE_DEVELOPMENT.md`](architecture/CONTEXT_MODULE_DEVELOPMENT.md) | 上下文裁剪、摘要、恢复策略及调研 |
| [`MESSAGE_CONTEXT_AND_COMPACTION.md`](architecture/MESSAGE_CONTEXT_AND_COMPACTION.md) | 每轮消息、模型历史、协议修复与压缩细节 |
| [`SESSION_PERSISTENCE.md`](architecture/SESSION_PERSISTENCE.md) | SQLite、消息和会话持久化 |
| [`COMPLETION_GUARD.md`](architecture/COMPLETION_GUARD.md) | 完成判定问题和修复 |
| [`TOOL_MESSAGE_PROTOCOL.md`](architecture/TOOL_MESSAGE_PROTOCOL.md) | `tool_use` / `tool_result` 协议与中断恢复 |
| [`AGENT_RUNTIME_AND_DIAGNOSTICS.md`](architecture/AGENT_RUNTIME_AND_DIAGNOSTICS.md) | 运行状态、日志和诊断 |

## testing：测试与证据

| 文档或目录 | 内容 |
| --- | --- |
| [`FULL_FUNCTION_REAL_API_TEST_2026-08-08.md`](testing/FULL_FUNCTION_REAL_API_TEST_2026-08-08.md) | 最新真实 DeepSeek 全功能验收 |
| [`ASTRACODE_UI_OBSERVABILITY_TEST_2026-08-08.md`](testing/ASTRACODE_UI_OBSERVABILITY_TEST_2026-08-08.md) | UI、Skill、Todo 和 Agent 监视器验收 |
| [`REAL_API_CRUD_TEST_2026-08-08.md`](testing/REAL_API_CRUD_TEST_2026-08-08.md) | 早期真实 CRUD 回归 |
| [`TODO_MODE_REAL_API_TEST_2026-08-09.md`](testing/TODO_MODE_REAL_API_TEST_2026-08-09.md) | Todo 强制模式修复和真实 API 测试 |
| [`evidence/`](testing/evidence/) | 脱敏的机器可读验收证据 |

## release：版本与发布

| 文档 | 内容 |
| --- | --- |
| [`GITHUB_RELEASE_GUIDE.md`](release/GITHUB_RELEASE_GUIDE.md) | Windows 安装包、GitHub Release 和公开发布清单 |
| [`PUBLIC_SOURCE_AUDIT_2026-10-11.md`](release/PUBLIC_SOURCE_AUDIT_2026-10-11.md) | 公开源码范围、隐私清理、验证结果与发布边界 |
| [`RELEASE_NOTES_0.8.0.md`](release/RELEASE_NOTES_0.8.0.md) | 0.8.0 功能、安装方式和边界 |
| [`RELEASE_NOTES_0.8.1.md`](release/RELEASE_NOTES_0.8.1.md) | 0.8.1 新手导览、文件卡片和主题修复 |

## 维护规则

- 开发相关修改必须同步更新 `product/PRODUCT_DESIGN.md` 和 `product/PRODUCT_DEVELOPMENT.md`。
- 真实线上模型测试写入 `testing/` 下的独立报告，脱敏原始数据放在 `testing/evidence/`。
- 文档引用使用相对路径，避免项目移动后失效。
- API Key、授权头、隐藏思考和敏感工作区内容不得进入文档或测试证据。
- 不要把新文档重新堆到本目录顶层；先判断它属于哪个分类。
