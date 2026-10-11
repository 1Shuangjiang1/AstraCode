export interface PromptTemplate {
  id: string;
  title: string;
  description: string;
  category: "开发" | "排障" | "文档" | "协作" | "学习" | "写作" | "分析" | "规划";
  content: string;
}

export const PROMPT_TEMPLATES: PromptTemplate[] = [
  {
    id: "feature", title: "实现代码功能", category: "开发", description: "目标、边界、验收与测试一次写清",
    content: `请在当前项目中实现以下功能：\n\n【目标】\n（要实现什么）\n\n【当前情况】\n（相关文件、已有行为或限制）\n\n【具体要求】\n1. \n2. \n\n【验收标准】\n- \n- \n\n请先检查现有实现并维护 Todo 列表，再进行修改；完成后运行与风险相称的测试，并说明改动文件、测试结果和剩余风险。`,
  },
  {
    id: "bugfix", title: "定位并修复问题", category: "排障", description: "从复现、根因到回归测试",
    content: `请排查并修复下面的问题：\n\n【现象】\n（错误信息或异常表现）\n\n【复现步骤】\n1. \n2. \n\n【预期行为】\n\n请先复现并阅读相关日志，找到根因后做最小且完整的修复；补充回归测试，并说明为什么此前会出错。`,
  },
  {
    id: "document", title: "编写技术文档", category: "文档", description: "面向读者、范围与示例",
    content: `请编写一份技术文档。\n\n【文档主题】\n\n【目标读者】\n\n【必须覆盖】\n- 背景与目标\n- 工作原理\n- 使用步骤与示例\n- 边界、常见问题与排障\n\n请先核对项目中的真实实现，不要凭空假设；使用清晰的 Markdown 结构并保存到合适的文档目录。`,
  },
  {
    id: "review", title: "只读代码审查", category: "排障", description: "加载 code-review Skill，不改文件",
    content: `请先调用 load_skill 加载 code-review，然后对指定代码做只读审查。重点检查正确性、并发与资源释放、安全边界、错误处理和测试缺口。请按严重程度列出问题，附文件位置和可执行的修复建议；不要直接修改文件。\n\n【审查范围】\n`,
  },
  {
    id: "parallel", title: "多子 Agent 调研", category: "协作", description: "把独立问题并行拆给多个 Explore Agent",
    content: `请先维护 Todo 列表。把下面相互独立的调研任务分别交给多个 Explore 子 Agent 并行完成，主 Agent 汇总证据、消除冲突后再给出结论；子 Agent 只读，不修改文件。\n\n【问题 A】\n\n【问题 B】\n\n【最终产出】\n`,
  },
  {
    id: "team", title: "Teammate 协作实现", category: "协作", description: "分配文件所有权并汇总验证",
    content: `请把任务拆成可以独立交付的部分，创建多个 teammate，明确每人的文件所有权、产出和验证方式，避免同时编辑同一文件。主 Agent 负责协调、检查消息与最终集成测试。\n\n【总目标】\n\n【可拆分模块】\n`,
  },
  {
    id: "background", title: "后台运行任务", category: "开发", description: "启动长任务并轮询结果",
    content: `请使用 background_run 在后台启动下面的长任务，不要阻塞主流程；记录 task_id，并用 check_background 定期检查直至完成。若失败，读取输出定位原因。\n\n【命令与目的】\n`,
  },
  {
    id: "learning-roadmap", title: "制定学习路线", category: "学习", description: "按基础、时间和目标安排阶段任务",
    content: `请为我制定一份可执行的学习路线。\n\n【学习主题】\n\n【我的基础】\n\n【可投入时间】\n（例如：每天 1 小时，共 8 周）\n\n【最终目标】\n\n请将路线拆成阶段，说明每阶段的核心概念、练习任务、推荐产出和自测标准；控制信息密度，优先保留真正影响进步的内容。`,
  },
  {
    id: "concept-tutor", title: "讲懂一个概念", category: "学习", description: "从直觉、例子到自测逐层解释",
    content: `请像一位耐心的老师一样讲解下面的概念。\n\n【概念】\n\n【我的当前理解】\n\n【希望达到的程度】\n（入门了解 / 能实际应用 / 能向别人解释）\n\n先用直觉和生活类比建立认识，再给出准确解释、典型例子、常见误区和 3 道由浅入深的自测题。不要堆砌术语。`,
  },
  {
    id: "article-draft", title: "撰写文章初稿", category: "写作", description: "明确读者、观点和风格后成文",
    content: `请撰写一篇文章初稿。\n\n【主题】\n\n【目标读者】\n\n【核心观点】\n\n【语气与风格】\n（例如：专业但易懂、轻松、有故事感）\n\n【篇幅与必须包含的信息】\n\n请先组织清晰的叙事结构，再完成正文；避免空话、重复表达和生硬的小标题，必要时使用具体例子增强说服力。`,
  },
  {
    id: "polish-writing", title: "润色与改写", category: "写作", description: "保留原意，改善结构、节奏和表达",
    content: `请润色下面的内容。\n\n【用途与读者】\n\n【希望的风格】\n\n【必须保留的信息】\n\n【原文】\n（粘贴原文）\n\n请保持事实和原意不变，修复逻辑跳跃、冗余、歧义和不自然表达。先给出完成稿，再用简短清单说明最重要的调整。`,
  },
  {
    id: "decision-analysis", title: "方案对比与决策", category: "分析", description: "基于约束比较选项并给出建议",
    content: `请帮助我分析并选择方案。\n\n【需要做的决定】\n\n【候选方案】\nA. \nB. \nC. \n\n【关键约束】\n（预算、时间、风险、维护成本等）\n\n【我最看重的因素】\n\n请先明确评价维度和权重，再比较收益、成本、风险和可逆性；给出推荐方案、适用前提，以及什么条件变化时应改选其他方案。`,
  },
  {
    id: "material-summary", title: "材料提炼与摘要", category: "分析", description: "提取结论、证据、分歧和行动项",
    content: `请分析并提炼下面的材料。\n\n【使用目的】\n（快速理解 / 汇报 / 决策 / 复习）\n\n【希望的摘要长度】\n\n【材料】\n（粘贴内容或说明文件位置）\n\n请区分事实、观点和推断，输出核心结论、关键证据、重要数据、存在的分歧或不确定性，以及可以采取的下一步行动。不要只是按段落复述。`,
  },
  {
    id: "project-plan", title: "制定项目计划", category: "规划", description: "把目标拆成里程碑、依赖和验收",
    content: `请为下面的项目制定一份现实可执行的计划。\n\n【项目目标】\n\n【截止时间】\n\n【人员与资源】\n\n【已知约束】\n\n【当前进度】\n\n请拆分里程碑和任务，标明依赖关系、负责人建议、时间估算、交付物和验收标准；列出前三项主要风险、预警信号和应对方案，并给出本周可以立即开始的行动。`,
  },
  {
    id: "meeting-notes", title: "整理会议纪要", category: "规划", description: "从讨论中提取决策、责任人与期限",
    content: `请把下面的会议内容整理成便于推进工作的纪要。\n\n【会议主题与日期】\n\n【参会角色】\n\n【原始记录】\n（粘贴聊天、速记或转写内容）\n\n请输出：会议目标、关键讨论、已经确认的决策、尚未解决的问题，以及行动项表格（任务、负责人、截止时间、依赖）。不明确的信息标注“待确认”，不要自行编造。`,
  },
  {
    id: "todo-execution", title: "Todo 分步执行", category: "规划", description: "强制创建 Todo 并逐项推进完整任务",
    content: `请使用 TodoWrite 工具管理并完成下面的任务。\n\n【任务目标】\n\n【具体要求】\n1. \n2. \n\n【验收标准】\n- \n- \n\n开始执行前，先把完整任务拆成 3–7 个清晰、可验证的 Todo 步骤；同一时间只能有一个步骤处于 in_progress。每完成一步就立即调用 TodoWrite 更新状态，再开始下一步。TodoWrite 只负责记录进度，不能代替 write_file、edit_file、bash 等实际工作；不要反复改写清单或只创建清单。全部步骤完成后，检查最终产出并汇报每一步的实际结果。`,
  },
];
