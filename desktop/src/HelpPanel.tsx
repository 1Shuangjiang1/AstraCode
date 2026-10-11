import { useEffect, useState } from "react";
import { Bot, Check, CircleHelp, Copy, ListChecks, MessageSquare, Sparkles, Users, Wrench, X } from "lucide-react";
import type { ToolInfo } from "./types";

type Language = "zh" | "en";

interface HelpPanelProps { open: boolean; tools: ToolInfo[]; onClose: () => void; }

const recipes = {
  zh: [
    { icon: <ListChecks size={16}/>, title: "让 Agent 持续维护 Todo", prompt: "先把任务拆成 Todo 列表，执行过程中及时更新状态，全部完成后再给我总结。" },
    { icon: <Bot size={16}/>, title: "调用一个子 Agent", prompt: "请调用 Explore 子 Agent，独立调查权限系统的实现位置，只返回相关文件、关键发现和风险，不要修改代码。" },
    { icon: <Users size={16}/>, title: "组织多个 Teammate", prompt: "把任务拆给两个 teammate：一个检查后端，一个检查 UI。让他们共享进度，最后由主 Agent 汇总并完成修改。" },
    { icon: <Sparkles size={16}/>, title: "先规划、后执行", prompt: "先切到 Plan 模式，阅读相关代码并给出分步方案、风险和验证方式；等我确认后再执行。" },
    { icon: <MessageSquare size={16}/>, title: "主动压缩长对话", prompt: "请压缩当前上下文，保留目标、约束、已修改文件、验证结果、未解决问题和下一步。" },
    { icon: <Wrench size={16}/>, title: "运行后台任务", prompt: "在后台运行完整测试，同时继续检查代码；测试结束后读取结果并处理失败项。" },
  ],
  en: [
    { icon: <ListChecks size={16}/>, title: "Keep a live Todo list", prompt: "Break this task into a Todo list first. Update each item while working, then summarize only after all items are complete." },
    { icon: <Bot size={16}/>, title: "Use a focused subagent", prompt: "Use an Explore subagent to locate the permission-system implementation. Return only relevant files, findings, and risks; do not edit files." },
    { icon: <Users size={16}/>, title: "Coordinate teammates", prompt: "Split the work between two teammates: one reviews the backend and one reviews the UI. Share progress, then let the lead agent integrate and verify the changes." },
    { icon: <Sparkles size={16}/>, title: "Plan before acting", prompt: "Start in Plan mode. Inspect the relevant code and give me steps, risks, and verification. Wait for my approval before implementing." },
    { icon: <MessageSquare size={16}/>, title: "Compact a long task", prompt: "Compact the current context while preserving the goal, constraints, changed files, verification results, open issues, and next steps." },
    { icon: <Wrench size={16}/>, title: "Run work in background", prompt: "Run the full test suite in the background while you continue reviewing the code. Check the result later and address any failures." },
  ],
};

const zhToolDescriptions: Record<string, string> = {
  set_working_directory: "在纯聊天模式中选择后续文件操作使用的目录。",
  bash: "运行可自动结束的 PowerShell 命令。",
  read_file: "读取文件内容。", list_directory: "列出目录内容。", path_exists: "检查路径是否存在。",
  write_file: "写入或创建文件。", edit_file: "精确替换文件中的一段内容。", delete_file: "删除单个文件。",
  TodoWrite: "维护当前任务的短期检查清单。", task: "启动一个拥有独立上下文的子 Agent。",
  load_skill: "加载一组专门的工作说明。", compress: "主动总结并压缩当前对话上下文。",
  background_run: "在后台运行命令。", check_background: "查看后台命令的状态和结果。",
  task_create: "创建可持久化的任务。", task_get: "读取某个任务。", task_update: "更新任务状态或依赖。", task_list: "列出全部持久化任务。",
  spawn_teammate: "启动一名可协作的队友 Agent。", list_teammates: "查看队友状态。", send_message: "给队友发送消息。",
  read_inbox: "读取主 Agent 收件箱。", broadcast: "向全部队友广播消息。", shutdown_request: "请求队友安全退出。",
  plan_approval: "批准或驳回队友提交的计划。", idle: "声明当前没有可执行工作。", claim_task: "认领一个持久化任务。",
};

export function HelpPanel({ open, tools, onClose }: HelpPanelProps) {
  const [language, setLanguage] = useState<Language>("zh");
  const [copied, setCopied] = useState("");
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close); return () => document.removeEventListener("keydown", close);
  }, [open, onClose]);
  if (!open) return null;

  async function copyPrompt(prompt: string, title: string) {
    await navigator.clipboard.writeText(prompt); setCopied(title);
    window.setTimeout(() => setCopied(""), 1300);
  }

  return <div className="modal-layer help-layer" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="help-panel" role="dialog" aria-modal="true" aria-labelledby="help-title">
      <header className="help-header">
        <div className="help-title-mark"><CircleHelp size={18}/></div>
        <div><p className="eyebrow">AGENT FIELD GUIDE</p><h2 id="help-title">{language === "zh" ? "如何指挥 AstraCode" : "How to direct AstraCode"}</h2></div>
        <div className="language-toggle" aria-label="Help language"><button className={language === "zh" ? "selected" : ""} onClick={() => setLanguage("zh")}>中文</button><button className={language === "en" ? "selected" : ""} onClick={() => setLanguage("en")}>EN</button></div>
        <button className="icon-button" aria-label="关闭帮助" onClick={onClose}><X size={16}/></button>
      </header>
      <div className="help-scroll">
        <section className="help-intro">
          <span>01</span><div><h3>{language === "zh" ? "不需要背工具名" : "You do not need to memorize tools"}</h3><p>{language === "zh" ? "直接说清目标、边界和验收条件即可。下面的提示词用于明确触发复杂工作流；权限策略仍会在真正执行工具时生效。" : "Describe the goal, boundaries, and acceptance criteria. The recipes below make advanced workflows explicit; your permission policy still governs every tool execution."}</p></div>
        </section>
        <div className="help-section-heading"><span>{language === "zh" ? "提示词配方" : "Prompt recipes"}</span><small>CLICK TO COPY</small></div>
        <section className="recipe-grid">{recipes[language].map((item) => <article key={item.title} className="recipe-card"><div className="recipe-icon">{item.icon}</div><div><h3>{item.title}</h3><p>{item.prompt}</p></div><button aria-label={`${language === "zh" ? "复制" : "Copy"} ${item.title}`} onClick={() => void copyPrompt(item.prompt, item.title)}>{copied === item.title ? <Check size={14}/> : <Copy size={14}/>}</button></article>)}</section>
        <div className="help-section-heading tool-heading"><span>{language === "zh" ? `当前可用工具 · ${tools.length}` : `Available tools · ${tools.length}`}</span><small>LIVE TOOLLIST</small></div>
        <section className="help-tool-grid">{tools.map((tool) => <article key={tool.name}><code>{tool.name}</code><p>{language === "zh" ? zhToolDescriptions[tool.name] || tool.description : tool.description}</p></article>)}</section>
      </div>
    </section>
  </div>;
}
