import { useEffect, useState } from "react";
import { Activity, Bot, Check, CircleDot, Users, Wrench, X } from "lucide-react";
import type { AgentActivity } from "./types";

function statusLabel(status: string) {
  return ({ started: "已启动", thinking: "思考中", working: "工作中", idle: "等待中", completed: "已完成", failed: "失败", shutdown: "已停止" } as Record<string, string>)[status] || status;
}

export function AgentMonitor({ open, agents, onClose }: { open: boolean; agents: AgentActivity[]; onClose: () => void }) {
  const [selected, setSelected] = useState(agents[0]?.id || "");
  useEffect(() => { if (!agents.some((agent) => agent.id === selected)) setSelected(agents[0]?.id || ""); }, [agents, selected]);
  useEffect(() => {
    if (!open) return; const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", escape); return () => window.removeEventListener("keydown", escape);
  }, [open, onClose]);
  if (!open) return null;
  const active = agents.find((agent) => agent.id === selected) || agents[0];
  return <div className="modal-layer agent-monitor-layer" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="agent-monitor" role="dialog" aria-modal="true" aria-label="Agent 工作监视器">
      <header><div><p>LIVE OR HISTORY</p><h2>Agent 工作监视器</h2></div><button className="icon-button" onClick={onClose}><X size={16}/></button></header>
      <div className="agent-monitor-body">
        <nav>{agents.length ? agents.map((agent) => <button key={agent.id} className={agent.id === active?.id ? "active" : ""} onClick={() => setSelected(agent.id)}><span className={`agent-kind ${agent.kind}`}>{agent.kind === "teammate" ? <Users size={14}/> : <Bot size={14}/>}</span><span><strong>{agent.name}</strong><small>{agent.kind === "teammate" ? "Teammate" : "Subagent"} · {statusLabel(agent.status)}</small></span><i className={`status-dot ${agent.status}`}/></button>) : <div className="agent-monitor-empty"><Users size={20}/><p>当前对话还没有调用子 Agent 或 Teammate。</p></div>}</nav>
        <main>{active ? <><div className="agent-detail-head"><div><span>{active.kind === "teammate" ? "TEAMMATE" : "SUBAGENT"}</span><h3>{active.name}</h3><p>{active.role}{active.round ? ` · 第 ${active.round} 轮` : ""}</p></div><strong className={`agent-status ${active.status}`}>{statusLabel(active.status)}</strong></div><div className="agent-assignment"><span>任务</span><p>{active.prompt || "等待任务说明"}</p></div><div className="agent-event-list">{active.events.map((event) => <article key={event.id} className={event.ok === false ? "failed" : ""}><span>{event.type.includes("tool") ? <Wrench size={13}/> : event.type.includes("completed") ? <Check size={13}/> : event.type.includes("message") ? <CircleDot size={13}/> : <Activity size={13}/>}</span><div><strong>{event.label}</strong>{event.detail && <p>{event.detail}</p>}</div><time>{new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></article>)}</div></> : <div className="agent-detail-empty">选择一个 Agent 查看工作记录。</div>}</main>
      </div>
    </section>
  </div>;
}
