import { useEffect, useRef, useState } from "react";
import { ArrowLeft, BookOpen, Braces, Check, FileText, LayoutTemplate, Lightbulb, ListTodo, PenLine, SearchCode, Users, X } from "lucide-react";
import { PROMPT_TEMPLATES, type PromptTemplate } from "./promptTemplates";

const categoryIcons = { 开发: Braces, 排障: SearchCode, 文档: FileText, 协作: Users, 学习: BookOpen, 写作: PenLine, 分析: Lightbulb, 规划: ListTodo };

export function PromptTemplateMenu({ open, onToggle, onSelect }: { open: boolean; onToggle: () => void; onSelect: (item: PromptTemplate) => void }) {
  const root = useRef<HTMLDivElement>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const [selected, setSelected] = useState<PromptTemplate | null>(null);
  const [draft, setDraft] = useState("");
  const [category, setCategory] = useState<string>("全部");
  const categories = ["全部", ...Array.from(new Set(PROMPT_TEMPLATES.map((item) => item.category)))];
  const visible = category === "全部" ? PROMPT_TEMPLATES : PROMPT_TEMPLATES.filter((item) => item.category === category);

  useEffect(() => {
    if (!open) { setSelected(null); setDraft(""); setCategory("全部"); return; }
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) onToggle(); };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (selected) { setSelected(null); setDraft(""); } else onToggle();
    };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open, onToggle, selected]);

  useEffect(() => { if (selected) requestAnimationFrame(() => editor.current?.focus()); }, [selected]);

  function choose(item: PromptTemplate) { setSelected(item); setDraft(item.content); }
  function confirm() {
    if (!selected || !draft.trim()) return;
    onSelect({ ...selected, content: draft.trim() });
    setSelected(null); setDraft("");
  }

  return <div className="template-picker" ref={root}>
    <button type="button" className="composer-tool-button" aria-expanded={open} title="选择 Prompt 模板" onClick={onToggle}><LayoutTemplate size={14}/><span>模板</span></button>
    {open && <section className={`template-menu ${selected ? "editing" : "browsing"}`} aria-label="Prompt 模板">
      {selected ? <>
        <header className="template-editor-head"><button type="button" className="template-back" onClick={() => { setSelected(null); setDraft(""); }} aria-label="返回模板列表"><ArrowLeft size={15}/></button><div><strong>{selected.title}</strong><small>直接补充、删除或重写，确认后再填入对话框</small></div><button type="button" className="template-close" onClick={onToggle} aria-label="关闭模板"><X size={15}/></button></header>
        <div className="template-editor-body"><div className="template-editor-label"><span>{selected.category}模板</span><small>{draft.length} 字符</small></div><textarea ref={editor} value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="编辑模板内容" spellCheck={false}/></div>
        <footer className="template-editor-actions"><button type="button" onClick={() => { setSelected(null); setDraft(""); }}>取消编辑</button><button type="button" className="template-confirm" disabled={!draft.trim()} onClick={confirm}><Check size={14}/>确认填入</button></footer>
      </> : <>
        <header><div><strong>任务模板</strong><small>选择一个模板，在大编辑器中完善后再填入</small></div><kbd>ESC</kbd></header>
        <nav className="template-categories" aria-label="模板分类">{categories.map((item) => <button type="button" className={category === item ? "selected" : ""} key={item} onClick={() => setCategory(item)}>{item}</button>)}</nav>
        <div className="template-list">{visible.map((item) => {
          const Icon = categoryIcons[item.category];
          return <button type="button" key={item.id} onClick={() => choose(item)}><span className="template-icon"><Icon size={15}/></span><span><strong>{item.title}</strong><small>{item.description}</small></span><em>{item.category}</em></button>;
        })}</div>
      </>}
    </section>}
  </div>;
}
