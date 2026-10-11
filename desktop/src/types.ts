export type AgentMode = "agent" | "plan";
export type PermissionMode = "safe" | "approval" | "full_access";
export type ThinkingEffort = "none" | "high" | "max";
export type VerificationMode = "off" | "standard" | "strict";
export type WorkspaceMode = "project" | "chat";
export type ThemeMode = "dark" | "light" | "system";
export type ConnectionState = "connecting" | "ready" | "error" | "stopped";

export interface SidecarEvent {
  type: string;
  timestamp: string;
  request_id?: string;
  session_id?: string;
  [key: string]: unknown;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface ProjectEntry {
  id: string;
  name: string;
  path: string;
  createdAt?: string;
  updatedAt?: string;
}

export type PlanState = "planning" | "waiting_for_review" | "revising" | "executing" | "verifying" | "completed" | "cancelled" | "failed";

export interface PlanStep {
  id: string;
  title: string;
  description: string;
  files: string[];
  verification: string;
  status: "pending" | "in_progress" | "completed" | "failed";
}

export interface PlanRecord {
  id: string;
  revision: number;
  state: PlanState;
  title: string;
  summary: string;
  assumptions: string[];
  steps: PlanStep[];
  risks: string[];
  verification: string[];
}

export interface ConversationEntry {
  id: string;
  workspaceKey: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  schemaVersion: 1;
  status: "idle" | "running" | "completed" | "cancelled" | "interrupted" | "error";
  model?: string;
  permission?: PermissionMode;
  thinkingEffort?: ThinkingEffort;
  projectPath?: string;
  activeDirectory?: string;
  pinned: boolean;
  archived: boolean;
  summary?: string;
  summaryUpdatedAt?: string;
  contextTokens?: number;
  lastDiagnosticLog?: string;
  plan?: PlanRecord;
  todos?: TodoItem[];
  agents?: AgentActivity[];
  changeSet?: ChangeSet;
  verification?: VerificationRecord;
  messages: ChatMessage[];
  timeline: Array<SidecarEvent & { uiId: string }>;
}

export interface ChangedFile {
  path: string;
  status: "created" | "modified" | "deleted";
  additions: number;
  deletions: number;
  diff?: string;
  before_preview?: string;
  after_preview?: string;
}

export interface ChangeSet {
  id: string;
  state: string;
  root?: string;
  manifest_path?: string;
  files: ChangedFile[];
  totals: { files: number; additions: number; deletions: number };
  rollback?: { ok?: boolean; state: string; restored?: string[]; conflicts?: string[] };
}

export interface VerificationRecord {
  mode: VerificationMode;
  verdict: "pass" | "needs_fix" | "blocked";
  passed: boolean;
  summary: string;
  confidence?: number;
  checks: Array<{ name: string; status: string; evidence: string }>;
  issues: Array<{ severity: string; message: string; path?: string }>;
}

export interface RecoveryRun {
  request_id: string;
  session_id: string;
  state: string;
  phase: string;
  prompt: string;
  updated_at: string;
  checkpoint: { last_event?: string; pending_tool?: { tool?: string; detail?: string }; completed_tools?: Array<{ tool?: string; ok?: boolean }> };
}

export interface ToolInfo {
  name: string;
  description: string;
}

export interface SkillInfo {
  name: string;
  description: string;
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
  activeForm?: string;
}

export interface AgentActivityEvent {
  id: string;
  type: string;
  timestamp: string;
  label: string;
  detail?: string;
  ok?: boolean;
}

export interface AgentActivity {
  id: string;
  kind: "subagent" | "teammate";
  name: string;
  role: string;
  prompt: string;
  status: string;
  round?: number;
  startedAt: string;
  updatedAt: string;
  summary?: string;
  events: AgentActivityEvent[];
}

export interface RuntimeSettings {
  model: string;
  title_model: string;
  title_base_url: string;
  title_api_key_configured: boolean;
  base_url: string;
  api_key_configured: boolean;
  command_timeout: number;
}
