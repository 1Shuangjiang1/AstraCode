import { Check, KeyRound, Moon, Settings, Sun, Wrench, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { RuntimeSettings, ThemeMode, ToolInfo } from "./types";

interface Props {
  open: boolean;
  theme: ThemeMode;
  settings: RuntimeSettings;
  tools: ToolInfo[];
  saving: boolean;
  onClose: () => void;
  onTheme: (theme: ThemeMode) => void;
  onSave: (settings: RuntimeSettings, apiKey: string, titleApiKey: string) => void;
}

export function SettingsPanel({ open, theme, settings, tools, saving, onClose, onTheme, onSave }: Props) {
  const [draft, setDraft] = useState(settings);
  const [apiKey, setApiKey] = useState("");
  const [titleApiKey, setTitleApiKey] = useState("");
  useEffect(() => { setDraft(settings); setApiKey(""); setTitleApiKey(""); }, [settings, open]);
  if (!open) return null;

  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="settings-panel" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header className="settings-header">
          <div><p className="eyebrow">WORKBENCH CONTROL</p><h2 id="settings-title"><Settings size={17} /> 设置</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭设置"><X size={17} /></button>
        </header>

        <div className="settings-scroll">
          <section className="settings-group">
            <div className="settings-label"><span>外观</span><small>即时生效</small></div>
            <div className="theme-options">
              {(["dark", "light", "system"] as ThemeMode[]).map((value) => (
                <button key={value} className={theme === value ? "selected" : ""} onClick={() => onTheme(value)}>
                  {value === "dark" ? <Moon size={16} /> : value === "light" ? <Sun size={16} /> : <Settings size={16} />}
                  <span>{value === "dark" ? "深色" : value === "light" ? "浅色" : "跟随系统"}</span>
                  {theme === value && <Check size={14} />}
                </button>
              ))}
            </div>
          </section>

          <section className="settings-group">
            <div className="settings-label"><span>DeepSeek 接入</span><small>{settings.api_key_configured ? "KEY 已配置" : "尚未配置"}</small></div>
            <label className="field"><span>模型 ID</span><input value={draft.model} onChange={(e) => setDraft((value) => ({ ...value, model: e.target.value }))} /></label>
            <label className="field"><span>Anthropic Base URL</span><input value={draft.base_url} onChange={(e) => setDraft((value) => ({ ...value, base_url: e.target.value }))} /></label>
            <label className="field"><span><KeyRound size={13} /> 替换 API Key</span><input type="password" value={apiKey} autoComplete="new-password" placeholder={settings.api_key_configured ? "留空则保持当前 Key" : "输入 DeepSeek API Key"} onChange={(e) => setApiKey(e.target.value)} /></label>
            <div className="settings-label"><span>自动命名 · 硅基流动</span><small>{settings.title_api_key_configured ? "KEY 已配置" : "尚未配置"}</small></div>
            <label className="field"><span>对话命名模型</span><input value={draft.title_model} onChange={(e) => setDraft((value) => ({ ...value, title_model: e.target.value }))} /></label>
            <label className="field"><span>OpenAI Base URL</span><input value={draft.title_base_url} onChange={(e) => setDraft((value) => ({ ...value, title_base_url: e.target.value }))} /></label>
            <label className="field"><span><KeyRound size={13} /> 替换命名 API Key</span><input type="password" value={titleApiKey} autoComplete="new-password" placeholder={settings.title_api_key_configured ? "留空则保持当前 Key" : "输入硅基流动 API Key"} onChange={(e) => setTitleApiKey(e.target.value)} /></label>
            <label className="field compact"><span>命令超时（秒）</span><input type="number" min={5} max={600} value={draft.command_timeout} onChange={(e) => setDraft((value) => ({ ...value, command_timeout: Number(e.target.value) }))} /></label>
            <button className="primary-action" disabled={saving} onClick={() => onSave(draft, apiKey, titleApiKey)}>{saving ? "保存中…" : "保存模型配置"}</button>
            <p className="settings-note">自动命名使用独立的硅基流动接口与 Key，并强制关闭思考、限制极短输出；即使命名服务不可用，主任务仍会继续并使用本地备用标题。API Key 仅写入本机被忽略的 `.env`。</p>
          </section>

          <section className="settings-group tool-catalog">
            <div className="settings-label"><span><Wrench size={13} /> 可用工具</span><small>{tools.length} TOOLS</small></div>
            <div className="tool-list">
              {tools.map((tool) => <div key={tool.name}><code>{tool.name}</code><p>{tool.description}</p></div>)}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
