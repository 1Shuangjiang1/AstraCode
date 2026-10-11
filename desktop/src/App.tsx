import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity, Archive, ArchiveRestore, Bot, Brain, Bug, Check, ChevronDown, ChevronUp, CircleDot, ExternalLink,
  FolderOpen, ListChecks, MessageSquare, MoreHorizontal, Pin, Plus, Send, Settings, Shield, ShieldCheck,
  CircleHelp, PencilLine, Play, Sparkles, Square, SquareTerminal, Trash2, Users, Waypoints, Wrench, X,
  PanelLeftClose, PanelLeftOpen, GripVertical, FileDiff, FileText, RotateCcw, BookOpen,
} from "lucide-react";
import { AgentMonitor } from "./AgentMonitor";
import { HelpPanel } from "./HelpPanel";
import { PromptTemplateMenu } from "./PromptTemplateMenu";
import { SettingsPanel } from "./SettingsPanel";
import { SkillCommandMenu } from "./SkillCommandMenu";
import { DiffPreview } from "./DiffPreview";
import { OnboardingGuide } from "./OnboardingGuide";
import { WorkbenchBridge } from "./transport";
import type {
  AgentActivity, AgentMode, ConnectionState, ConversationEntry, PermissionMode, ProjectEntry,
  ChangeSet, PlanRecord, RecoveryRun, RuntimeSettings, SidecarEvent, SkillInfo, ThemeMode, ThinkingEffort, ToolInfo, VerificationMode, VerificationRecord, WorkspaceMode,
} from "./types";

type TimelineEvent = ConversationEntry["timeline"][number];
type ApprovalRequest = SidecarEvent & { approval_id: string; tool: string; reason: string; risk: string; args?: true };

const WELCOME = `工作台已连接 **DeepSeek V4 Flash**。

- 在左侧切换“项目”或“纯聊天”
- 使用项目旁的 **+** 创建独立对话
- 模型、权限和思考强度可在输入框下方切换`;

const permissionLabels: Record<PermissionMode, string> = {
  safe: "安全模式", approval: "需要审批", full_access: "完全访问",
};
const modeOptions = [
  { value: "agent" as const, label: "Agent", detail: "直接执行任务" },
  { value: "plan" as const, label: "Plan", detail: "只生成计划" },
];
const permissionOptions = [
  { value: "safe" as const, label: "安全", detail: "只允许低风险读取" },
  { value: "approval" as const, label: "审批", detail: "跨目录和高风险需确认" },
  { value: "full_access" as const, label: "完全访问", detail: "自动执行非关键操作" },
];
const thinkingOptions = [
  { value: "none" as const, label: "快速", detail: "关闭思考，响应最快" },
  { value: "high" as const, label: "High", detail: "平衡速度与推理" },
  { value: "max" as const, label: "Max", detail: "复杂任务深度推理" },
];
const verificationOptions = [
  { value: "off" as const, label: "不验证", detail: "跳过独立 Verifier" },
  { value: "standard" as const, label: "标准验证", detail: "经济地核对需求与证据" },
  { value: "strict" as const, label: "严格验证", detail: "独立 AI 读取变更并检查" },
];
const timelineEventTypes = new Set(["session_started", "status", "tool_started", "tool_completed", "plan_created", "plan_state_changed", "context_compacted", "agent_started", "agent_completed", "agent_failed", "verification_started", "verification_completed", "change_set_ready", "rollback_completed", "task_completed", "task_incomplete", "task_cancelled", "task_interrupted", "error"]);
const agentEventTypes = new Set(["agent_started", "agent_status", "agent_message", "agent_tool_started", "agent_tool_completed", "agent_completed", "agent_failed"]);

function stored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || "") as T; } catch { return fallback; }
}

function makeConversation(workspaceKey: string): ConversationEntry {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(), workspaceKey, title: "新对话", createdAt: now, updatedAt: now,
    schemaVersion: 1, status: "idle", pinned: false, archived: false,
    messages: [{ id: `welcome-${now}`, role: "assistant", content: WELCOME, timestamp: now }], timeline: [], todos: [], agents: [],
  };
}

function shortPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path;
}

function normalizeConversation(item: ConversationEntry): ConversationEntry {
  return {
    ...item, updatedAt: item.updatedAt || item.createdAt, schemaVersion: 1,
    status: item.status || "idle", pinned: Boolean(item.pinned), archived: Boolean(item.archived),
    messages: item.messages || [], timeline: item.timeline || [], todos: item.todos || [], agents: item.agents || [],
    changeSet: item.changeSet, verification: item.verification,
  };
}

function orderedSessions(items: ConversationEntry[], includeArchived = false) {
  return items.filter((item) => includeArchived ? item.archived : !item.archived).sort((a, b) =>
    Number(b.pinned) - Number(a.pinned) || b.updatedAt.localeCompare(a.updatedAt));
}

interface SessionCardProps {
  session: ConversationEntry; index: number; active: boolean; running: boolean; menuOpen: boolean; archived?: boolean;
  onSelect: () => void; onMenu: () => void; onPin: () => void; onArchive: () => void; onDelete: () => void;
}

function SessionCard({ session, index, active, running, menuOpen, archived, onSelect, onMenu, onPin, onArchive, onDelete }: SessionCardProps) {
  const menuButton = useRef<HTMLButtonElement>(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  useEffect(() => {
    if (!menuOpen || !menuButton.current) return;
    const place = () => {
      const rect = menuButton.current!.getBoundingClientRect();
      const below = rect.bottom + 6;
      setMenuPosition({ top: below + 108 <= window.innerHeight ? below : Math.max(8, rect.top - 114), left: Math.max(8, rect.right - 148) });
    };
    place();
    window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [menuOpen]);
  return <div className={`session-card-shell ${menuOpen ? "menu-open" : ""}`}>
    <button disabled={running || archived} onClick={onSelect} className={`session-card ${active ? "active" : ""}`}>
      <span className="session-index">{String(index + 1).padStart(2, "0")}</span>
      <span className="session-copy"><span className="session-title-fade" title={session.title}><strong>{session.title}</strong></span><small>{active ? running ? "正在运行" : "当前会话" : `${session.messages.length} 条消息`}</small></span>
      {active && running ? <i className="running-dot"/> : session.pinned ? <Pin className="pin-mark" size={11} fill="currentColor"/> : null}
    </button>
    <button ref={menuButton} disabled={running} className="session-menu-trigger" aria-label={`${session.title} 的会话操作`} aria-expanded={menuOpen} onClick={onMenu}><MoreHorizontal size={14}/></button>
    {menuOpen && createPortal(<div className="session-actions" role="menu" style={menuPosition}>
      {!archived && <button role="menuitem" onClick={onPin}><Pin size={13}/>{session.pinned ? "取消置顶" : "置顶"}</button>}
      <button role="menuitem" onClick={onArchive}>{archived ? <ArchiveRestore size={13}/> : <Archive size={13}/>} {archived ? "恢复到侧边栏" : "归档"}</button>
      <button role="menuitem" className="danger" onClick={onDelete}><Trash2 size={13}/>删除</button>
    </div>, document.body)}
  </div>;
}

interface QuickPickerProps<T extends string> {
  id: string; label: string; value: T;
  options: Array<{ value: T; label: string; detail: string }>;
  icon: React.ReactNode; open: boolean; onToggle: () => void; onChange: (value: T) => void;
}

function QuickPicker<T extends string>({ id, label, value, options, icon, open, onToggle, onChange }: QuickPickerProps<T>) {
  const root = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value) || options[0];
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) onToggle(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onToggle(); };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open, onToggle]);
  return <div className={`quick-picker ${open ? "open" : ""}`} ref={root}>
    <button type="button" className="quick-picker-trigger" aria-label={`${label}：${selected.label}`} aria-expanded={open} onClick={onToggle}>
      {icon}<span>{selected.label}</span><ChevronUp size={12} />
    </button>
    {open && <div className="quick-picker-menu" id={`${id}-menu`} role="listbox" aria-label={label}>
      <div className="picker-caption">{label}</div>
      {options.map((option) => <button type="button" role="option" aria-selected={option.value === value} className={option.value === value ? "selected" : ""} key={option.value} onClick={() => onChange(option.value)}>
        <span className="picker-check">{option.value === value && <Check size={12} />}</span>
        <span><strong>{option.label}</strong><small>{option.detail}</small></span>
      </button>)}
    </div>}
  </div>;
}

function eventTitle(event: SidecarEvent) {
  if (event.type === "session_started") return "会话已建立";
  if (event.type === "status") return String(event.message || "Agent 状态更新");
  if (event.type === "tool_started") return String(event.label || event.tool || "工具开始执行");
  if (event.type === "tool_completed") return event.ok === false ? `${String(event.tool || "工具")} 执行失败` : `${String(event.tool || "工具")} 已完成`;
  if (event.type === "plan_created") return String(event.title || "计划已生成");
  if (event.type === "plan_state_changed") return `计划状态：${String(event.state || "updated")}`;
  if (event.type === "context_compacted") return "上下文已压缩并生成摘要";
  if (event.type === "agent_started") return `${String(event.name || "子 Agent")} 已启动`;
  if (event.type === "agent_completed") return `${String(event.name || "子 Agent")} 已完成`;
  if (event.type === "agent_failed") return `${String(event.name || "子 Agent")} 执行失败`;
  if (event.type === "task_completed") return String(event.summary || "任务完成");
  if (event.type === "task_incomplete") return String(event.message || "任务尚未完成");
  if (event.type === "task_cancelled") return "任务已取消";
  if (event.type === "task_interrupted") return "任务已中断，可安全继续";
  if (event.type === "verification_started") return "独立 Verifier 开始检查";
  if (event.type === "verification_completed") return event.passed ? "验证通过" : "验证未通过";
  if (event.type === "change_set_ready") return "修改清单已生成";
  if (event.type === "rollback_completed") return event.ok === false ? "撤销存在冲突" : "修改已撤销";
  if (event.type === "error") return String(event.message || "发生错误");
  return event.type;
}

function eventIcon(event: SidecarEvent) {
  if (["tool_started", "tool_completed"].includes(event.type)) return <Wrench size={14} />;
  if (event.type === "plan_created") return <ListChecks size={14} />;
  if (event.type === "plan_state_changed") return <Sparkles size={14} />;
  if (event.type === "task_completed" || event.type === "agent_completed") return <Check size={14} />;
  if (["agent_started", "agent_failed"].includes(event.type)) return <Users size={14} />;
  if (["task_incomplete", "error"].includes(event.type)) return <CircleDot size={14} />;
  return <Activity size={14} />;
}

export default function App() {
  const bridge = useRef(new WorkbenchBridge());
  const currentRequestId = useRef<string | null>(null);
  const activeConversationRef = useRef<string | null>(null);
  const projectsRef = useRef<ProjectEntry[]>([]);
  const conversationsRef = useRef<ConversationEntry[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>(() => stored("sfull.workspaceMode", "project"));
  const [projects, setProjects] = useState<ProjectEntry[]>(() => stored("sfull.projects", []));
  const [activeProjectId, setActiveProjectId] = useState(() => stored("sfull.activeProjectId", ""));
  const [conversations, setConversations] = useState<ConversationEntry[]>(() => stored<ConversationEntry[]>("sfull.conversations", []).map(normalizeConversation));
  const [activeConversationId, setActiveConversationId] = useState(() => stored("sfull.activeConversationId", ""));
  const [mode, setMode] = useState<AgentMode>(() => stored("sfull.agentMode", "agent"));
  const [permission, setPermission] = useState<PermissionMode>(() => stored("sfull.permission", "approval"));
  const [thinkingEffort, setThinkingEffort] = useState<ThinkingEffort>(() => stored("sfull.thinking", "high"));
  const [verificationMode, setVerificationMode] = useState<VerificationMode>(() => stored("astracode.verification", "standard"));
  const [theme, setTheme] = useState<ThemeMode>(() => stored("sfull.theme", "light"));
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings>({ model: "deepseek-v4-flash", title_model: "deepseek-ai/DeepSeek-V4-Flash", title_base_url: "https://api.siliconflow.cn/v1", title_api_key_configured: false, base_url: "https://api.deepseek.com/anthropic", api_key_configured: false, command_timeout: 30 });
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [libraryReady, setLibraryReady] = useState(false);
  const [sessionMenu, setSessionMenu] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [openPicker, setOpenPicker] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<SkillInfo | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [forceTodo, setForceTodo] = useState(false);
  const [agentMonitorOpen, setAgentMonitorOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => stored("sfull.sidebarCollapsed", false));
  const [sidebarWidth, setSidebarWidth] = useState(() => stored("sfull.sidebarWidth", 256));
  const [resizingSidebar, setResizingSidebar] = useState(false);
  const [running, setRunning] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  const [lastError, setLastError] = useState("");
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [planFeedback, setPlanFeedback] = useState("");
  const [executionExpanded, setExecutionExpanded] = useState(() => stored("sfull.executionExpanded", true));
  const [debugMode, setDebugMode] = useState(() => stored("sfull.debugMode", false));
  const [recoveries, setRecoveries] = useState<RecoveryRun[]>([]);
  const [diffOpen, setDiffOpen] = useState(false);
  const [previewPath, setPreviewPath] = useState<string | undefined>();
  const [previewTab, setPreviewTab] = useState<"diff" | "preview">("preview");
  const [undoing, setUndoing] = useState(false);

  const workspaceKey = workspaceMode === "chat" ? "chat" : `project:${activeProjectId}`;
  const activeProject = projects.find((item) => item.id === activeProjectId);
  const activeConversation = conversations.find((item) => item.id === activeConversationId);
  const messages = activeConversation?.messages || [];
  const timeline = activeConversation?.timeline || [];
  const todos = activeConversation?.todos || [];
  const agentActivities = activeConversation?.agents || [];
  const slashMatch = prompt.match(/(?:^|\s)\/([\w-]*)$/);
  const skillQuery = slashMatch?.[1] || "";
  const archivedSessions = orderedSessions(conversations.filter((item) => item.workspaceKey === workspaceKey), true);
  const latestDiagnosticLog = activeConversation?.lastDiagnosticLog || [...timeline].reverse().find((event) => typeof event.diagnostic_log === "string")?.diagnostic_log as string | undefined;
  const activeRecovery = recoveries.find((item) => item.session_id === activeConversationId);
  const generatedFiles = (activeConversation?.changeSet?.files || []).filter((file) => file.status !== "deleted");

  function updateConversation(id: string, updater: (value: ConversationEntry) => ConversationEntry) {
    setConversations((current) => current.map((item) => item.id === id ? updater(item) : item));
  }

  function ensureConversation(key: string) {
    const existing = orderedSessions(conversations.filter((item) => item.workspaceKey === key))[0];
    if (existing) { setActiveConversationId(existing.id); activeConversationRef.current = existing.id; return; }
    const created = makeConversation(key);
    setConversations((current) => [...current, created]);
    setActiveConversationId(created.id); activeConversationRef.current = created.id;
  }

  useEffect(() => {
    const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = theme === "system" ? (systemDark ? "dark" : "light") : theme;
    localStorage.setItem("sfull.theme", JSON.stringify(theme));
  }, [theme]);
  useEffect(() => { localStorage.setItem("sfull.projects", JSON.stringify(projects)); }, [projects]);
  useEffect(() => { localStorage.setItem("sfull.conversations", JSON.stringify(conversations)); }, [conversations]);
  useEffect(() => { projectsRef.current = projects; }, [projects]);
  useEffect(() => { conversationsRef.current = conversations; }, [conversations]);
  useEffect(() => { localStorage.setItem("sfull.workspaceMode", JSON.stringify(workspaceMode)); }, [workspaceMode]);
  useEffect(() => { localStorage.setItem("sfull.activeProjectId", JSON.stringify(activeProjectId)); }, [activeProjectId]);
  useEffect(() => { localStorage.setItem("sfull.activeConversationId", JSON.stringify(activeConversationId)); }, [activeConversationId]);
  useEffect(() => { localStorage.setItem("sfull.agentMode", JSON.stringify(mode)); }, [mode]);
  useEffect(() => { localStorage.setItem("sfull.permission", JSON.stringify(permission)); }, [permission]);
  useEffect(() => { localStorage.setItem("sfull.thinking", JSON.stringify(thinkingEffort)); }, [thinkingEffort]);
  useEffect(() => { localStorage.setItem("astracode.verification", JSON.stringify(verificationMode)); }, [verificationMode]);
  useEffect(() => { localStorage.setItem("sfull.executionExpanded", JSON.stringify(executionExpanded)); }, [executionExpanded]);
  useEffect(() => { localStorage.setItem("sfull.debugMode", JSON.stringify(debugMode)); }, [debugMode]);
  useEffect(() => { localStorage.setItem("sfull.sidebarCollapsed", JSON.stringify(sidebarCollapsed)); }, [sidebarCollapsed]);
  useEffect(() => { localStorage.setItem("sfull.sidebarWidth", JSON.stringify(sidebarWidth)); }, [sidebarWidth]);
  useEffect(() => {
    if (libraryReady && (workspaceMode === "chat" || activeProjectId) && (!activeConversation || activeConversation.workspaceKey !== workspaceKey || activeConversation.archived)) ensureConversation(workspaceKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceKey, libraryReady]);
  useEffect(() => { setShowArchived(false); setSessionMenu(null); }, [workspaceKey]);
  useEffect(() => { activeConversationRef.current = activeConversationId || null; }, [activeConversationId]);
  useEffect(() => {
    if (!libraryReady || connection !== "ready") return;
    const timer = window.setTimeout(() => { void bridge.current.send({ command: "save_library", request_id: crypto.randomUUID(), projects, conversations }); }, 220);
    return () => window.clearTimeout(timer);
  }, [projects, conversations, libraryReady, connection]);

  useEffect(() => {
    let active = true;
    const onEvent = (event: SidecarEvent) => {
      if (!active) return;
      if (event.type === "ready") {
        setConnection("ready");
        void bridge.current.send({ command: "get_settings", request_id: crypto.randomUUID() });
        void bridge.current.send({ command: "get_tools", request_id: crypto.randomUUID() });
        void bridge.current.send({ command: "get_skills", request_id: crypto.randomUUID() });
        void bridge.current.send({ command: "get_library", request_id: crypto.randomUUID() });
        void bridge.current.send({ command: "get_recovery", request_id: crypto.randomUUID() });
      }
      if (event.type === "sidecar_exit") setConnection("stopped");
      if (event.type === "settings_snapshot") { setRuntimeSettings(event as unknown as RuntimeSettings); setSettingsSaving(false); }
      if (event.type === "tools_snapshot" && Array.isArray(event.tools)) setTools(event.tools as ToolInfo[]);
      if (event.type === "skills_snapshot" && Array.isArray(event.skills)) setSkills(event.skills as SkillInfo[]);
      if (event.type === "recovery_snapshot" && Array.isArray(event.runs)) setRecoveries(event.runs as RecoveryRun[]);
      if (event.type === "recovery_dismissed") setRecoveries((items) => items.filter((item) => item.request_id !== String(event.target_request_id)));
      if (event.type === "library_snapshot") {
        const incomingProjects = Array.isArray(event.projects) ? event.projects as unknown as ProjectEntry[] : [];
        const incomingConversations = Array.isArray(event.conversations) ? (event.conversations as unknown as ConversationEntry[]).map(normalizeConversation) : [];
        if (incomingProjects.length || incomingConversations.length) {
          setProjects(incomingProjects);
          setConversations(incomingConversations);
          const first = incomingConversations.find((item) => item.id === activeConversationId && !item.archived)
            || orderedSessions(incomingConversations.filter((item) => item.workspaceKey === workspaceKey))[0]
            || orderedSessions(incomingConversations)[0];
          if (first) {
            setActiveConversationId(first.id);
            if (first.workspaceKey === "chat") setWorkspaceMode("chat");
            else { setWorkspaceMode("project"); setActiveProjectId(first.workspaceKey.slice(8)); }
          } else if (incomingProjects[0]) { setWorkspaceMode("project"); setActiveProjectId(incomingProjects[0].id); setActiveConversationId(""); }
          else { setWorkspaceMode("chat"); setActiveConversationId(""); }
        } else if (projectsRef.current.length || conversationsRef.current.length) {
          void bridge.current.send({ command: "save_library", request_id: crypto.randomUUID(), projects: projectsRef.current, conversations: conversationsRef.current });
        }
        setLibraryReady(true);
      }
      if (event.type === "approval_required") setApproval(event as ApprovalRequest);
      const conversationId = String(event.session_id || activeConversationRef.current || "");
      if (conversationId && typeof event.diagnostic_log === "string") {
        updateConversation(conversationId, (item) => ({ ...item, lastDiagnosticLog: event.diagnostic_log as string }));
      }
      if (event.type === "session_title_updated" && conversationId) {
        updateConversation(conversationId, (item) => ({ ...item, title: String(event.title || item.title), updatedAt: event.timestamp }));
      }
      if (event.type === "assistant_message" && conversationId) {
        updateConversation(conversationId, (item) => ({ ...item, updatedAt: event.timestamp, messages: [...item.messages, { id: `${conversationId}-${event.timestamp}`, role: "assistant", content: String(event.content || ""), timestamp: event.timestamp }] }));
      }
      if (event.type === "context_compacted" && conversationId) {
        updateConversation(conversationId, (item) => ({ ...item, summary: String(event.summary || ""), summaryUpdatedAt: event.timestamp, contextTokens: Number(event.estimatedTokens || 0) }));
      }
      if (event.type === "todo_updated" && conversationId && Array.isArray(event.items)) {
        updateConversation(conversationId, (item) => ({ ...item, updatedAt: event.timestamp, todos: event.items as ConversationEntry["todos"] }));
      }
      if ((event.type === "change_set_ready" || event.type === "rollback_completed") && conversationId && event.change_set) {
        updateConversation(conversationId, (item) => ({ ...item, changeSet: event.change_set as ChangeSet }));
        setUndoing(false);
      }
      if (event.type === "verification_completed" && conversationId) {
        updateConversation(conversationId, (item) => ({ ...item, verification: event as unknown as VerificationRecord }));
      }
      if (conversationId && agentEventTypes.has(event.type)) {
        updateConversation(conversationId, (item) => {
          const id = String(event.agent_id || `${event.agent_kind || "subagent"}:${event.name || "agent"}`);
          const current = item.agents || [];
          const existing = current.find((agent) => agent.id === id);
          const kind = event.agent_kind === "teammate" ? "teammate" : "subagent";
          const status = event.type === "agent_failed" ? "failed" : event.type === "agent_completed" ? "completed" : String(event.status || (event.type === "agent_started" ? "started" : existing?.status || "working"));
          const label = event.type === "agent_message" ? "Agent 回复" : event.type === "agent_tool_started" ? `${String(event.tool || "工具")} 开始` : event.type === "agent_tool_completed" ? `${String(event.tool || "工具")} ${event.ok === false ? "失败" : "完成"}` : event.type === "agent_started" ? "Agent 已启动" : event.type === "agent_completed" ? "工作已完成" : event.type === "agent_failed" ? "工作失败" : `状态：${status}`;
          const detail = String(event.content || event.result || event.error || event.detail || event.summary || "").slice(0, 4000) || undefined;
          const activity: AgentActivity = {
            id, kind, name: String(event.name || existing?.name || id), role: String(event.role || existing?.role || (kind === "teammate" ? "teammate" : "Explore")),
            prompt: String(event.prompt || existing?.prompt || ""), status, round: Number(event.round || existing?.round || 0) || undefined,
            startedAt: existing?.startedAt || event.timestamp, updatedAt: event.timestamp,
            summary: event.type === "agent_completed" ? String(event.summary || "") : existing?.summary,
            events: [...(existing?.events || []).slice(-79), { id: `${event.type}-${event.timestamp}-${Math.random()}`, type: event.type, timestamp: event.timestamp, label, detail, ok: event.ok as boolean | undefined }],
          };
          return { ...item, updatedAt: event.timestamp, agents: existing ? current.map((agent) => agent.id === id ? activity : agent) : [...current, activity] };
        });
      }
      if (event.type === "plan_created" && conversationId) {
        const plan = {
          id: String(event.id || event.plan_id || ""), revision: Number(event.revision || 1),
          state: String(event.state || "waiting_for_review"), title: String(event.title || "执行计划"),
          summary: String(event.summary || ""), assumptions: Array.isArray(event.assumptions) ? event.assumptions : [],
          steps: Array.isArray(event.steps) ? event.steps : [], risks: Array.isArray(event.risks) ? event.risks : [],
          verification: Array.isArray(event.verification) ? event.verification : [],
        } as PlanRecord;
        updateConversation(conversationId, (item) => ({ ...item, plan }));
      }
      if (event.type === "plan_state_changed" && conversationId) {
        updateConversation(conversationId, (item) => item.plan ? ({ ...item, plan: {
          ...item.plan, state: String(event.state || item.plan.state) as PlanRecord["state"],
          steps: Array.isArray(event.steps) && event.steps.length ? event.steps as PlanRecord["steps"] : item.plan.steps,
        } }) : item);
        if (["planning", "revising", "executing", "verifying"].includes(String(event.state))) setRunning(true);
        if (["waiting_for_review", "completed", "cancelled", "failed"].includes(String(event.state))) {
          setRunning(false); setStopRequested(false); currentRequestId.current = null;
        }
      }
      const isTaskEvent = Boolean(event.session_id) || event.request_id === currentRequestId.current;
      if (isTaskEvent && ["task_completed", "task_incomplete", "task_cancelled", "task_interrupted", "error"].includes(event.type)) {
        setRunning(false); setStopRequested(false); currentRequestId.current = null;
        if (conversationId) updateConversation(conversationId, (item) => ({ ...item, updatedAt: event.timestamp, status: event.type === "task_completed" ? "completed" : event.type === "task_cancelled" ? "cancelled" : event.type === "task_interrupted" ? "interrupted" : "error" }));
        if (event.type === "task_interrupted" && conversationId) void bridge.current.send({ command: "get_recovery", request_id: crypto.randomUUID() });
      }
      if (["task_incomplete", "error"].includes(event.type)) { setLastError(String(event.message || "未知错误")); setSettingsSaving(false); }
      if (conversationId && isTaskEvent && timelineEventTypes.has(event.type)) {
        updateConversation(conversationId, (item) => ({ ...item, updatedAt: event.timestamp, timeline: [...item.timeline.slice(-49), { ...event, uiId: `${event.type}-${event.timestamp}-${Math.random()}` }] }));
      }
    };
    bridge.current.connect(onEvent, (line) => console.info(`[sidecar] ${line}`)).then((defaultProject) => {
      if (!active) return;
      setProjects((current) => {
        if (current.length) { if (!activeProjectId) setActiveProjectId(current[0].id); return current; }
        const first = { id: crypto.randomUUID(), name: shortPath(defaultProject), path: defaultProject };
        setActiveProjectId(first.id); return [first];
      });
    }).catch((error: unknown) => { if (active) { setConnection("error"); setLastError(error instanceof Error ? error.message : String(error)); } });
    return () => { active = false; void bridge.current.disconnect(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const latestPlan = activeConversation?.plan;
  const completedTools = timeline.filter((event) => event.type === "tool_completed").length;

  async function addProject() {
    try {
      const path = await bridge.current.chooseProject(); if (!path) return;
      let project = projects.find((item) => item.path.toLowerCase() === path.toLowerCase());
      if (!project) { project = { id: crypto.randomUUID(), name: shortPath(path), path }; setProjects((current) => [...current, project!]); }
      setWorkspaceMode("project"); setActiveProjectId(project.id);
      const key = `project:${project.id}`;
      const session = conversations.find((item) => item.workspaceKey === key) || makeConversation(key);
      if (!conversations.some((item) => item.id === session.id)) setConversations((current) => [...current, session]);
      setActiveConversationId(session.id);
    } catch (error) { setLastError(error instanceof Error ? error.message : String(error)); }
  }

  function chooseWorkspace(nextMode: WorkspaceMode, projectId?: string) {
    if (running) return;
    const targetProjectId = projectId || activeProjectId || projects[0]?.id;
    if (nextMode === "project" && !targetProjectId) { void addProject(); return; }
    setWorkspaceMode(nextMode); if (targetProjectId) setActiveProjectId(targetProjectId);
    const key = nextMode === "chat" ? "chat" : `project:${targetProjectId}`;
    const existing = conversations.find((item) => item.workspaceKey === key);
    if (existing) setActiveConversationId(existing.id); else {
      const created = makeConversation(key); setConversations((current) => [...current, created]); setActiveConversationId(created.id);
    }
  }

  function newConversation(targetKey = workspaceKey) {
    if (running || (targetKey.startsWith("project:") && !targetKey.slice(8))) return;
    setSessionMenu(null);
    const created = makeConversation(targetKey); setConversations((current) => [...current, created]); setActiveConversationId(created.id);
    if (targetKey === "chat") setWorkspaceMode("chat"); else { setWorkspaceMode("project"); setActiveProjectId(targetKey.slice(8)); }
  }

  function selectConversation(session: ConversationEntry, projectId?: string) {
    if (running) return;
    setSessionMenu(null);
    if (projectId) { setWorkspaceMode("project"); setActiveProjectId(projectId); } else setWorkspaceMode("chat");
    setActiveConversationId(session.id);
  }

  function nextVisibleSession(excludedId: string, key: string) {
    return orderedSessions(conversations.filter((item) => item.id !== excludedId && item.workspaceKey === key))[0];
  }

  function togglePinned(session: ConversationEntry) {
    const pinned = !session.pinned; setSessionMenu(null);
    setConversations((current) => current.map((item) => item.id === session.id ? { ...item, pinned, updatedAt: new Date().toISOString() } : item));
    void bridge.current.send({ command: "set_session_state", request_id: crypto.randomUUID(), session_id: session.id, pinned });
  }

  function setArchived(session: ConversationEntry, archived: boolean) {
    setSessionMenu(null);
    setConversations((current) => current.map((item) => item.id === session.id ? { ...item, archived, pinned: archived ? false : item.pinned, updatedAt: new Date().toISOString() } : item));
    void bridge.current.send({ command: "set_session_state", request_id: crypto.randomUUID(), session_id: session.id, archived, ...(archived ? { pinned: false } : {}) });
    if (archived && session.id === activeConversationId) {
      const replacement = nextVisibleSession(session.id, session.workspaceKey);
      if (replacement) setActiveConversationId(replacement.id); else newConversation(session.workspaceKey);
    }
  }

  function deleteConversation(session: ConversationEntry) {
    if (!window.confirm(`确定永久删除“${session.title}”吗？\n\n消息、工具记录、模型上下文和本地事件日志都会被删除。`)) return;
    setSessionMenu(null);
    const replacement = nextVisibleSession(session.id, session.workspaceKey);
    setConversations((current) => current.filter((item) => item.id !== session.id));
    void bridge.current.send({ command: "delete_session", request_id: crypto.randomUUID(), session_id: session.id });
    if (session.id === activeConversationId) {
      if (replacement) setActiveConversationId(replacement.id); else newConversation(session.workspaceKey);
    }
  }

  function beginSidebarResize(event: React.PointerEvent<HTMLButtonElement>) {
    if (sidebarCollapsed) return;
    event.preventDefault();
    const startX = event.clientX; const startWidth = sidebarWidth;
    setResizingSidebar(true);
    const move = (next: PointerEvent) => setSidebarWidth(Math.max(220, Math.min(420, startWidth + next.clientX - startX)));
    const end = () => { setResizingSidebar(false); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", end);
  }

  function chooseSkill(skill: SkillInfo) {
    setSelectedSkill(skill);
    setPrompt((value) => value.replace(/(?:^|\s)\/[\w-]*$/, (match) => match.startsWith(" ") ? " " : ""));
  }

  async function startTask() {
    const value = prompt.trim(); if (!value || running || connection !== "ready" || !activeConversation) return;
    const inline = value.match(/^\/([\w-]+)\s+([\s\S]+)$/);
    const inlineSkill = inline ? skills.find((skill) => skill.name.toLowerCase() === inline[1].toLowerCase()) : undefined;
    const skill = selectedSkill || inlineSkill;
    const userValue = inlineSkill ? inline![2].trim() : value;
    const executionRequirements: string[] = [];
    if (skill) executionRequirements.push(`请先调用 load_skill 工具加载 \"${skill.name}\"，并严格遵循该 Skill 的工作流程。`);
    if (forceTodo) executionRequirements.push("本轮必须使用 TodoWrite 工具：执行前先把完整任务拆成 3–7 个清晰、可验证的步骤；同一时间只能有一个步骤为 in_progress；每完成一步立即调用 TodoWrite 更新状态后再继续。TodoWrite 只用于记录进度，不能代替 write_file、edit_file、bash 等完成任务所需的实际工具；不要反复改写清单或只创建清单，必须依次执行实际工作并完成所有步骤。");
    const modelValue = executionRequirements.length ? `<execution-requirements>\n${executionRequirements.join("\n")}\n</execution-requirements>\n\n用户任务：\n${userValue}` : userValue;
    const requestId = crypto.randomUUID(); currentRequestId.current = requestId;
    const startedAt = new Date().toISOString();
    updateConversation(activeConversation.id, (item) => ({ ...item, title: item.title === "新对话" ? userValue.slice(0, 24) : item.title, updatedAt: startedAt, status: "running", model: runtimeSettings.model, permission, thinkingEffort, projectPath: workspaceMode === "project" ? activeProject?.path : undefined, lastDiagnosticLog: undefined, timeline: [], todos: [], agents: [], changeSet: undefined, verification: undefined, messages: [...item.messages, { id: requestId, role: "user", content: userValue, timestamp: startedAt }] }));
    setLastError(""); setRunning(true); setPrompt(""); setSelectedSkill(null); setForceTodo(false);
    try {
      await bridge.current.send({ command: "start_task", request_id: requestId, session_id: activeConversation.id, workspace_key: activeConversation.workspaceKey, workspace_mode: workspaceMode, project_path: workspaceMode === "project" ? activeProject?.path || "" : "", prompt: modelValue, display_prompt: userValue, mode, permission, model: runtimeSettings.model, thinking_effort: thinkingEffort, todo_mode: forceTodo, verification_mode: verificationMode, failure_rollback: true, offline: false });
    } catch (error) { setRunning(false); currentRequestId.current = null; setLastError(error instanceof Error ? error.message : String(error)); }
  }

  async function stopTask() {
    if (!running || stopRequested) return; setStopRequested(true);
    try { await bridge.current.send({ command: "cancel_task", request_id: crypto.randomUUID(), target_request_id: currentRequestId.current }); }
    catch (error) { setStopRequested(false); setLastError(error instanceof Error ? error.message : String(error)); }
  }

  async function resumeTask(run: RecoveryRun) {
    if (running || !activeConversation) return;
    const requestId = crypto.randomUUID(); currentRequestId.current = requestId;
    setRunning(true); setLastError("");
    updateConversation(activeConversation.id, (item) => ({ ...item, status: "running", timeline: [] }));
    try {
      await bridge.current.send({ command: "resume_task", request_id: requestId, target_request_id: run.request_id });
      setRecoveries((items) => items.filter((item) => item.request_id !== run.request_id));
    } catch (error) { setRunning(false); setLastError(error instanceof Error ? error.message : String(error)); }
  }

  async function dismissRecovery(run: RecoveryRun) {
    await bridge.current.send({ command: "dismiss_recovery", request_id: crypto.randomUUID(), target_request_id: run.request_id });
    setRecoveries((items) => items.filter((item) => item.request_id !== run.request_id));
  }

  async function undoCurrentRun() {
    if (!activeConversation?.changeSet || undoing) return;
    if (!window.confirm("确定撤销本轮文件修改吗？后来被手动改过的文件不会被覆盖。")) return;
    setUndoing(true);
    await bridge.current.send({ command: "undo_run", request_id: crypto.randomUUID(), target_request_id: activeConversation.changeSet.id });
  }

  function openChangePreview(path?: string, tab: "diff" | "preview" = "preview") {
    setPreviewPath(path);
    setPreviewTab(tab);
    setDiffOpen(true);
  }

  async function revealGenerated(path?: string) {
    const root = activeConversation?.changeSet?.root;
    if (!root) { setLastError("本轮变更没有可用的项目根目录。"); return; }
    try { await bridge.current.revealWorkspaceItem(root, path); }
    catch (error) { setLastError(error instanceof Error ? error.message : String(error)); }
  }

  async function answerApproval(choice: "once" | "always" | "deny") {
    if (!approval) return;
    await bridge.current.send({ command: "approval_response", request_id: crypto.randomUUID(), approval_id: approval.approval_id, choice });
    setApproval(null);
  }

  async function respondToPlan(choice: "approve" | "revise" | "cancel") {
    if (!latestPlan || !activeConversation || running) return;
    if (choice === "revise" && !planFeedback.trim()) { setLastError("请先填写计划修改意见。"); return; }
    const requestId = crypto.randomUUID();
    currentRequestId.current = requestId;
    setLastError("");
    if (choice !== "cancel") setRunning(true);
    if (choice === "revise") {
      const value = planFeedback.trim();
      updateConversation(activeConversation.id, (item) => ({ ...item, messages: [...item.messages, {
        id: requestId, role: "user", content: `计划修改意见：${value}`, timestamp: new Date().toISOString(),
      }] }));
    }
    try {
      await bridge.current.send({ command: "plan_response", request_id: requestId,
        session_id: activeConversation.id, workspace_key: activeConversation.workspaceKey,
        plan_id: latestPlan.id, choice, feedback: planFeedback.trim() });
      setPlanFeedback("");
    } catch (error) {
      setRunning(false); currentRequestId.current = null;
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveSettings(next: RuntimeSettings, apiKey: string, titleApiKey: string) {
    setSettingsSaving(true);
    await bridge.current.send({ command: "update_settings", request_id: crypto.randomUUID(), model: next.model, title_model: next.title_model, title_base_url: next.title_base_url, title_api_key: titleApiKey, base_url: next.base_url, command_timeout: next.command_timeout, api_key: apiKey });
  }

  async function openLatestLog() {
    if (!latestDiagnosticLog) return;
    try { await bridge.current.revealLog(latestDiagnosticLog); }
    catch (error) { setLastError(error instanceof Error ? error.message : String(error)); }
  }

  return <div className={`workbench ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${resizingSidebar ? "resizing-sidebar" : ""}`} style={{ "--sidebar-width": `${sidebarCollapsed ? 66 : sidebarWidth}px` } as React.CSSProperties}>
    <header className="topbar">
      <div className="brand-block"><div className="brand-mark"><Waypoints size={21} /></div><div><p className="eyebrow">LOCAL AGENT WORKSPACE</p><h1>AstraCode <span>Workbench</span></h1></div></div>
      <div className="context-display" title={workspaceMode === "project" ? activeProject?.path : "不绑定固定工作目录"}>
        {workspaceMode === "chat" ? <MessageSquare size={16} /> : <FolderOpen size={16} />}
        <span><small>{workspaceMode === "chat" ? "PURE CHAT" : "ACTIVE PROJECT"}</small><strong>{workspaceMode === "chat" ? "纯聊天模式" : activeProject?.name || "尚未选择项目"}</strong></span>
      </div>
      <div className="runtime-controls"><button className={`debug-trigger ${debugMode ? "active" : ""}`} aria-pressed={debugMode} onClick={() => setDebugMode((value) => !value)} title="任务结束后显示本地日志入口"><Bug size={14}/><span>调试 {debugMode ? "ON" : "OFF"}</span></button><button className="guide-trigger" onClick={() => setGuideOpen(true)} title="第一次使用从这里开始"><BookOpen size={14}/><span>新手指南</span></button><button className="help-trigger" onClick={() => setHelpOpen(true)} aria-label="打开工具手册" title="工具与提示词手册"><CircleHelp size={15}/></button><button className="settings-trigger" onClick={() => setSettingsOpen(true)}><Settings size={15} /> 设置</button><div className={`connection-pill ${connection}`} title={lastError || "Python sidecar 状态"}><i />{connection === "ready" ? "SIDECAR ONLINE" : connection.toUpperCase()}</div></div>
    </header>

    <div className="workspace-grid">
      <aside className="session-rail">
        <button type="button" className="sidebar-collapse" aria-label={sidebarCollapsed ? "展开项目侧边栏" : "收起项目侧边栏"} title={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"} onClick={() => setSidebarCollapsed((value) => !value)}>{sidebarCollapsed ? <PanelLeftOpen size={17}/> : <PanelLeftClose size={17}/>}</button>
        {!sidebarCollapsed && <button type="button" className="sidebar-resizer" aria-label="调整侧边栏宽度" title="左右拖动调整宽度" onPointerDown={beginSidebarResize}><GripVertical size={13}/></button>}
        <div className="workspace-mode-toggle" role="tablist" aria-label="工作空间模式">
          <button role="tab" aria-selected={workspaceMode === "project"} className={workspaceMode === "project" ? "selected" : ""} onClick={() => chooseWorkspace("project")}><FolderOpen size={13}/>项目</button>
          <button role="tab" aria-selected={workspaceMode === "chat"} className={workspaceMode === "chat" ? "selected" : ""} onClick={() => chooseWorkspace("chat")}><MessageSquare size={13}/>纯聊天</button>
        </div>
        {workspaceMode === "project" ? <>
          <div className="rail-heading"><span>项目</span><button onClick={() => void addProject()} disabled={running} aria-label="添加项目路径" title="添加项目路径"><Plus size={15}/></button></div>
          <div className="project-tree">{projects.map((project) => {
            const projectSessions = orderedSessions(conversations.filter((session) => session.workspaceKey === `project:${project.id}`));
            const expanded = project.id === activeProjectId;
            return <section className={`project-group ${expanded ? "active" : ""}`} key={project.id}>
              <div className="project-row"><button className="project-select" disabled={running} onClick={() => chooseWorkspace("project", project.id)} title={project.path}><FolderOpen size={14}/><span><strong>{project.name}</strong><small>{project.path}</small></span></button><button className="project-add-chat" disabled={running} onClick={() => newConversation(`project:${project.id}`)} aria-label={`在 ${project.name} 中新建对话`} title="新建项目对话"><Plus size={14}/></button></div>
              {expanded && <div className="project-conversations">{projectSessions.map((session, index) => <SessionCard key={session.id} session={session} index={index} active={session.id === activeConversationId} running={running} menuOpen={sessionMenu === session.id} onSelect={() => selectConversation(session, project.id)} onMenu={() => setSessionMenu(sessionMenu === session.id ? null : session.id)} onPin={() => togglePinned(session)} onArchive={() => setArchived(session, true)} onDelete={() => deleteConversation(session)}/>)}</div>}
            </section>;
          })}</div>
          {!projects.length && <div className="rail-empty"><FolderOpen size={17}/><p>点击顶部 + 添加第一个项目。</p></div>}
        </> : <>
          <div className="rail-heading"><span>纯聊天</span><button onClick={() => newConversation("chat")} disabled={running} aria-label="新建聊天"><Plus size={15}/></button></div>
          <div className="session-list">{orderedSessions(conversations.filter((session) => session.workspaceKey === "chat")).map((session, index) => <SessionCard key={session.id} session={session} index={index} active={session.id === activeConversationId} running={running} menuOpen={sessionMenu === session.id} onSelect={() => selectConversation(session)} onMenu={() => setSessionMenu(sessionMenu === session.id ? null : session.id)} onPin={() => togglePinned(session)} onArchive={() => setArchived(session, true)} onDelete={() => deleteConversation(session)}/>)}</div>
        </>}
        {!!archivedSessions.length && <div className="archive-drawer"><button className="archive-toggle" onClick={() => setShowArchived((value) => !value)} aria-expanded={showArchived}><Archive size={13}/><span>已归档</span><small>{archivedSessions.length}</small><ChevronUp size={12}/></button>{showArchived && <div className="archived-list">{archivedSessions.map((session, index) => <SessionCard key={session.id} session={session} index={index} active={false} running={running} archived menuOpen={sessionMenu === session.id} onSelect={() => undefined} onMenu={() => setSessionMenu(sessionMenu === session.id ? null : session.id)} onPin={() => undefined} onArchive={() => setArchived(session, false)} onDelete={() => deleteConversation(session)}/>)}</div>}</div>}
        <div className="build-stamp"><span>BUILD</span><strong>0.8.1 / RELEASE PREVIEW</strong><small>{bridge.current.desktop ? "TAURI 2" : "BROWSER DEMO"}</small></div>
      </aside>

      <main className="conversation-panel">
        <div className="panel-titlebar"><div><p className="eyebrow">{workspaceMode === "chat" ? "UNBOUND CHAT" : "PROJECT THREAD"}</p><h2>{activeConversation?.title || "新对话"}</h2></div><div className="mode-badge"><Sparkles size={14} /> {workspaceMode === "chat" ? "按需选择目录" : "项目内执行"}</div></div>
        <section className="message-stream" aria-live="polite">
          {activeRecovery && <section className="recovery-card"><div><p className="eyebrow">SAFE RESUME</p><h3>上次任务在“{activeRecovery.phase}”阶段中断</h3><p>{activeRecovery.checkpoint.pending_tool ? `未确认的工具：${activeRecovery.checkpoint.pending_tool.tool || "未知"}。继续时会先检查工作区，不会直接重放。` : "已保存最后一个可靠检查点，可以从现状继续未完成工作。"}</p></div><div><button onClick={() => void dismissRecovery(activeRecovery)}>忽略</button><button className="resume-primary" onClick={() => void resumeTask(activeRecovery)}><Play size={13}/>安全继续</button></div></section>}
          {messages.map((message) => <article className={`message ${message.role}`} key={message.id}><div className="message-avatar">{message.role === "assistant" ? <Bot size={17} /> : "你"}</div><div className="message-body"><div className="message-meta"><strong>{message.role === "assistant" ? "AstraCode" : "你"}</strong><time>{new Date(message.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></div><div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a> }}>{message.content}</ReactMarkdown></div></div></article>)}
          {latestPlan && <section className={`plan-review-card state-${latestPlan.state}`} aria-label="计划审阅">
            <header><div><p className="eyebrow">PLAN V1 · REV {latestPlan.revision}</p><h3>{latestPlan.title}</h3></div><span className="plan-state-pill">{latestPlan.state.replaceAll("_", " ")}</span></header>
            <p className="plan-summary">{latestPlan.summary}</p>
            <div className="plan-step-stack">{latestPlan.steps.map((step, index) => <article key={step.id || `${step.title}-${index}`} className={`plan-step ${step.status}`}><span>{step.status === "completed" ? <Check size={13}/> : index + 1}</span><div><strong>{step.title}</strong><p>{step.description}</p>{step.files?.length > 0 && <small>涉及：{step.files.join(" · ")}</small>}<small>验证：{step.verification}</small></div></article>)}</div>
            {latestPlan.risks.length > 0 && <div className="plan-risks"><strong>风险</strong>{latestPlan.risks.map((risk) => <span key={risk}>{risk}</span>)}</div>}
            {latestPlan.state === "waiting_for_review" && <footer className="plan-review-actions"><textarea value={planFeedback} onChange={(event) => setPlanFeedback(event.target.value)} placeholder="可选：写下你希望调整的步骤、范围或验证方式…" aria-label="计划修改意见"/><div><button onClick={() => void respondToPlan("cancel")}><X size={14}/>取消计划</button><button onClick={() => void respondToPlan("revise")}><PencilLine size={14}/>要求修改</button><button className="approve-plan" onClick={() => void respondToPlan("approve")}><Play size={14} fill="currentColor"/>批准并执行</button></div></footer>}
          </section>}
          {!!timeline.length && <section className={`execution-block ${executionExpanded ? "expanded" : "collapsed"}`} aria-label="Agent 执行记录">
            <button className="execution-header" type="button" aria-expanded={executionExpanded} aria-controls="execution-timeline" onClick={() => setExecutionExpanded((value) => !value)}>
              <span><SquareTerminal size={15} /> 执行记录 <i>{timeline.length}</i></span>
              <span className="execution-header-meta"><small>{running ? "LIVE" : activeConversation?.status === "error" ? "INCOMPLETE" : activeConversation?.status === "cancelled" ? "CANCELLED" : "COMPLETE"}</small>{executionExpanded ? <ChevronUp size={14}/> : <ChevronDown size={14}/>}</span>
            </button>
            <div className="execution-body" id="execution-timeline" aria-hidden={!executionExpanded}><div className="execution-body-inner">
              {timeline.map((event) => <div className={`timeline-row ${event.type} ${event.ok === false ? "failed" : ""}`} key={event.uiId}><span className="timeline-icon">{eventIcon(event)}</span><div><strong>{eventTitle(event)}</strong>{typeof event.detail === "string" && event.detail && <p className="tool-detail">{event.detail}</p>}{typeof event.result === "string" && <p>{event.result}</p>}{event.type === "session_started" && <><p>{event.offline ? "离线演示" : "DeepSeek 在线"} · {permissionLabels[permission]} · 思考 {String(event.thinking_effort || thinkingEffort)}</p>{debugMode && typeof event.diagnostic_log === "string" && <p className="diagnostic-log" title={event.diagnostic_log}>日志：{event.diagnostic_log}</p>}</>}</div><time>{new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></div>)}
            </div></div>
            {debugMode && !running && latestDiagnosticLog && <footer className="execution-log-footer"><div><Bug size={14}/><span><strong>本次运行日志</strong><small title={latestDiagnosticLog}>{latestDiagnosticLog}</small></span></div><button type="button" onClick={() => void openLatestLog()}><ExternalLink size={13}/>打开日志</button></footer>}
          </section>}
          {activeConversation?.verification && <details className={`verification-compact ${activeConversation.verification.verdict}`}><summary><span><ShieldCheck size={13}/><strong>{activeConversation.verification.passed ? "验证通过" : "验证需注意"}</strong><small>{activeConversation.verification.mode.toUpperCase()}</small></span><ChevronDown size={12}/></summary><div><p>{activeConversation.verification.summary}</p>{activeConversation.verification.issues?.length > 0 && <ul>{activeConversation.verification.issues.map((issue, index) => <li key={index}>{issue.path ? `${issue.path}：` : ""}{issue.message}</li>)}</ul>}</div></details>}
          {activeConversation?.changeSet && activeConversation.changeSet.files.length > 0 && <section className="change-summary-card output-summary-card"><div className="output-summary-heading"><div className="output-summary-title"><span className="output-summary-icon"><FileText size={16}/></span><span><strong>{generatedFiles.length ? `${generatedFiles.length} 个本轮文件` : `${activeConversation.changeSet.totals.files} 个文件发生变化`}</strong><small><b>+{activeConversation.changeSet.totals.additions}</b><i>−{activeConversation.changeSet.totals.deletions}</i> · {activeConversation.changeSet.state === "rolled_back" ? "已撤销" : "可预览、定位或撤销"}</small></span></div><div className="output-summary-actions"><button className="file-action-primary" onClick={() => openChangePreview(undefined, "diff")}><FileDiff size={12}/>查看变更</button>{generatedFiles.length > 0 && activeConversation.changeSet.root && <button onClick={() => void revealGenerated()}><FolderOpen size={12}/>打开文件夹</button>}<button className="undo-inline" disabled={activeConversation.changeSet.state === "rolled_back" || undoing} onClick={() => void undoCurrentRun()}><RotateCcw size={12}/>{undoing ? "撤销中" : "撤销"}</button></div></div>{generatedFiles.length > 0 && <div className="output-file-list">{generatedFiles.slice(0, 6).map((file) => <button key={file.path} onClick={() => openChangePreview(file.path, "preview")} title={`预览 ${file.path}`}><FileText size={13}/><span>{file.path}</span><small>{/\.(?:md|markdown)$/i.test(file.path) ? "MARKDOWN" : file.status.toUpperCase()}</small></button>)}{generatedFiles.length > 6 && <button onClick={() => openChangePreview()}><span>其余 {generatedFiles.length - 6} 个文件</span></button>}</div>}</section>}
        </section>
        <div className="composer-zone">
          {lastError && <div className="error-banner">{lastError}</div>}
          <div className="composer">
            {slashMatch && !running && <SkillCommandMenu skills={skills} query={skillQuery} onSelect={chooseSkill} onClose={() => setPrompt((value) => value.replace(/(?:^|\s)\/[\w-]*$/, ""))}/>} 
            {selectedSkill && <div className="selected-skill"><Sparkles size={13}/><span>Skill · {selectedSkill.name}</span><button type="button" onClick={() => setSelectedSkill(null)} aria-label="移除 Skill"><X size={12}/></button></div>}
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void startTask(); } }} placeholder={workspaceMode === "chat" ? "直接聊天；输入 / 选择 Skill…" : mode === "plan" ? "描述目标，我会先给出可审阅的计划…" : "描述任务；输入 / 选择 Skill…"} rows={3} disabled={running} aria-label="任务内容"/>
            <div className="composer-footer"><div className="quick-controls">
              <PromptTemplateMenu open={templateOpen} onToggle={() => setTemplateOpen((value) => !value)} onSelect={(item) => { setPrompt(item.content); setTemplateOpen(false); }}/>
              <button type="button" className={`composer-tool-button todo-force-button ${forceTodo ? "active" : ""}`} aria-pressed={forceTodo} title={forceTodo ? "已要求本轮必须使用 TodoWrite 分步执行" : "要求本轮使用 TodoWrite 分步执行"} onClick={() => setForceTodo((value) => !value)}><ListChecks size={14}/><span>Todo</span></button>
              <QuickPicker id="mode-picker" label="运行模式" value={mode} options={modeOptions} icon={<Bot size={13}/>} open={openPicker === "mode"} onToggle={() => setOpenPicker(openPicker === "mode" ? null : "mode")} onChange={(value) => { setMode(value); setOpenPicker(null); }}/>
              <QuickPicker id="permission-picker" label="权限策略" value={permission} options={permissionOptions} icon={<Shield size={13}/>} open={openPicker === "permission"} onToggle={() => setOpenPicker(openPicker === "permission" ? null : "permission")} onChange={(value) => { setPermission(value); setOpenPicker(null); }}/>
              <QuickPicker id="thinking-picker" label="思考强度" value={thinkingEffort} options={thinkingOptions} icon={<Brain size={13}/>} open={openPicker === "thinking"} onToggle={() => setOpenPicker(openPicker === "thinking" ? null : "thinking")} onChange={(value) => { setThinkingEffort(value); setOpenPicker(null); }}/>
              <QuickPicker id="verification-picker" label="完成验证" value={verificationMode} options={verificationOptions} icon={<ShieldCheck size={13}/>} open={openPicker === "verification"} onToggle={() => setOpenPicker(openPicker === "verification" ? null : "verification")} onChange={(value) => { setVerificationMode(value); setOpenPicker(null); }}/>
              <span className="model-chip">{runtimeSettings.model}</span>
            </div><button className={`send-button ${running ? "cancel" : ""}`} onClick={() => running ? void stopTask() : void startTask()} disabled={running ? stopRequested : (!prompt.trim() || connection !== "ready" || !activeConversation)}>{running ? stopRequested ? <Activity className="spin" size={16}/> : <Square size={14} fill="currentColor"/> : <Send size={16}/>} {running ? stopRequested ? "正在停止" : "停止任务" : mode === "plan" ? "生成计划" : "开始任务"}</button></div>
          </div><p className="composer-hint">Ctrl + Enter 发送 · 输入 / 使用 Skill · {workspaceMode === "chat" ? "聊天空间" : activeProject?.name} · {thinkingEffort === "none" ? "不思考" : `思考 ${thinkingEffort}`}</p>
        </div>
      </main>

      <aside className="inspector-panel">
        <div className="inspector-heading"><div><p className="eyebrow">INSPECTOR</p><h2>运行概览</h2></div><Activity size={18}/></div>
        <section className="metric-grid"><div><span>状态</span><strong>{running ? "运行中" : activeConversation?.status === "error" ? "未完成" : activeConversation?.status === "cancelled" ? "已取消" : timeline.length ? "已完成" : "待命"}</strong></div><div><span>工具</span><strong>{String(completedTools).padStart(2, "0")}</strong></div><div><span>空间</span><strong>{workspaceMode === "chat" ? "CHAT" : "PROJECT"}</strong></div><div><span>权限</span><strong className="low-risk">{permission === "approval" ? "ASK" : permission === "safe" ? "SAFE" : "FULL"}</strong></div></section>
        <section className="inspector-section"><div className="section-label"><ListChecks size={15}/><span>Todo 进度</span><small>{todos.filter((item) => item.status === "completed").length}/{todos.length}</small></div>{todos.length ? <div className="todo-panel"><div className="todo-progress"><i style={{ width: `${Math.round(todos.filter((item) => item.status === "completed").length / todos.length * 100)}%` }}/></div>{todos.map((item, index) => <div className={`todo-row ${item.status}`} key={`${item.content}-${index}`}><span>{item.status === "completed" ? <Check size={11}/> : item.status === "in_progress" ? <Activity size={11}/> : index + 1}</span><p title={item.content}>{item.status === "in_progress" && item.activeForm ? item.activeForm : item.content}</p></div>)}</div> : <div className="empty-state compact"><ListChecks size={17}/><p>调用 TodoWrite 后会实时显示进度。</p></div>}</section>
        <section className="inspector-section"><div className="section-label"><Users size={15}/><span>Agent 协作</span><small>{agentActivities.length || "EMPTY"}</small></div>{agentActivities.length ? <div className="agent-summary-list">{agentActivities.slice(0, 4).map((agent) => <button key={agent.id} onClick={() => setAgentMonitorOpen(true)}><span className={`status-dot ${agent.status}`}/><span><strong title={agent.name}>{agent.name}</strong><small>{agent.kind === "teammate" ? "Teammate" : "Subagent"} · {agent.status}</small></span></button>)}<button className="open-agent-monitor" onClick={() => setAgentMonitorOpen(true)}>打开工作监视器</button></div> : <div className="empty-state compact"><Users size={17}/><p>子 Agent 和 Teammate 会显示在这里。</p></div>}</section>
        <section className="inspector-section"><div className="section-label"><ShieldCheck size={15}/><span>安全边界</span></div><div className="safety-card"><div className="safety-line"><Check size={13}/><span>{workspaceMode === "chat" ? "跨目录前按权限审批" : "路径限制在当前项目"}</span></div><div className="safety-line"><Check size={13}/><span>DeepSeek 官方 API</span></div><div className="safety-line"><Check size={13}/><span>主 Agent 与队友共用策略</span></div></div></section>
        <section className="inspector-section"><div className="section-label"><ListChecks size={15}/><span>计划</span><small>{latestPlan ? "ACTIVE" : "EMPTY"}</small></div>{latestPlan && Array.isArray(latestPlan.steps) ? <div className="plan-list">{(latestPlan.steps as Array<{title:string;status:string}>).map((step, index) => <div className={step.status} key={`${step.title}-${index}`}><span>{step.status === "completed" ? <Check size={12}/> : index + 1}</span><p>{step.title}</p></div>)}</div> : <div className="empty-state compact"><ListChecks size={17}/><p>Plan 模式的步骤会显示在这里。</p></div>}</section>
        {activeConversation?.summary && <section className="inspector-section"><div className="section-label"><Brain size={15}/><span>上下文摘要</span><small>~{activeConversation.contextTokens || 0} TOKENS</small></div><div className="context-summary">{activeConversation.summary}</div></section>}
      </aside>
    </div>

    <SettingsPanel open={settingsOpen} theme={theme} settings={runtimeSettings} tools={tools} saving={settingsSaving} onClose={() => setSettingsOpen(false)} onTheme={setTheme} onSave={(next, key, titleKey) => void saveSettings(next, key, titleKey)}/>
    <OnboardingGuide open={guideOpen} onClose={() => setGuideOpen(false)} onOpenSettings={() => setSettingsOpen(true)}/>
    <HelpPanel open={helpOpen} tools={tools} onClose={() => setHelpOpen(false)}/>
    <AgentMonitor open={agentMonitorOpen} agents={agentActivities} onClose={() => setAgentMonitorOpen(false)}/>
    <DiffPreview open={diffOpen} changeSet={activeConversation?.changeSet} undoing={undoing} initialPath={previewPath} initialTab={previewTab} onClose={() => setDiffOpen(false)} onUndo={() => void undoCurrentRun()} onReveal={(path) => void revealGenerated(path)}/>
    {approval && <div className="modal-layer approval-layer"><section className="approval-dialog" role="alertdialog" aria-modal="true"><header><div className="approval-icon"><Shield size={20}/></div><div><p className="eyebrow">PERMISSION REQUEST</p><h2>需要你的批准</h2></div><button className="icon-button" onClick={() => void answerApproval("deny")}><X size={16}/></button></header><div className="approval-body"><div><span>执行者</span><strong>{String(approval.actor || "lead")}</strong></div><div><span>工具</span><strong>{approval.tool}</strong></div><div><span>风险</span><strong className="risk-high">{approval.risk.toUpperCase()}</strong></div><p>{approval.reason}</p>{approval.args && <pre>{JSON.stringify(approval.args, null, 2)}</pre>}</div><footer><button onClick={() => void answerApproval("deny")}>拒绝</button><button onClick={() => void answerApproval("once")}>仅本次允许</button><button className="approve" onClick={() => void answerApproval("always")}>本会话同类允许</button></footer></section></div>}
  </div>;
}
