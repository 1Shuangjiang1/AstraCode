import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, FileDiff, FileText, FolderOpen, RotateCcw, X } from "lucide-react";
import type { ChangeSet } from "./types";

type PreviewTab = "diff" | "preview";

export function DiffPreview({ changeSet, open, undoing, initialPath, initialTab = "preview", onClose, onUndo, onReveal }: {
  changeSet?: ChangeSet;
  open: boolean;
  undoing: boolean;
  initialPath?: string;
  initialTab?: PreviewTab;
  onClose: () => void;
  onUndo: () => void;
  onReveal: (path?: string) => void;
}) {
  const [selected, setSelected] = useState(0);
  const [tab, setTab] = useState<PreviewTab>(initialTab);
  useEffect(() => {
    if (!open || !changeSet) return;
    const index = initialPath ? changeSet.files.findIndex((file) => file.path === initialPath) : -1;
    setSelected(index >= 0 ? index : 0);
    setTab(initialTab);
  }, [open, changeSet?.id, initialPath, initialTab]);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open, onClose]);
  const file = changeSet?.files[selected];
  const markdown = useMemo(() => Boolean(file && /\.(?:md|markdown)$/i.test(file.path)), [file]);
  if (!open || !changeSet) return null;
  const rolledBack = changeSet.state === "rolled_back" || changeSet.state === "rollback_partial";
  const preview = file?.after_preview || (file?.status === "deleted" ? "文件已删除。" : "没有可预览的文本。");

  return <div className="modal-layer diff-layer" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="diff-dialog" role="dialog" aria-modal="true" aria-labelledby="file-preview-title">
      <header><div><p className="eyebrow">CHANGESET · {changeSet.id.slice(0, 8)}</p><h2 id="file-preview-title">生成内容与文件变更</h2></div><div className="diff-totals"><span>{changeSet.totals.files} 文件</span><b>+{changeSet.totals.additions}</b><i>-{changeSet.totals.deletions}</i></div><button className="icon-button" aria-label="关闭文件预览" onClick={onClose}><X size={16}/></button></header>
      <div className="diff-layout">
        <aside>{changeSet.files.map((item, index) => <button key={item.path} className={index === selected ? "selected" : ""} onClick={() => { setSelected(index); setTab("preview"); }}><FileText size={14}/><span title={item.path}>{item.path}</span><small className={item.status}>{item.status}</small><b>+{item.additions} −{item.deletions}</b></button>)}</aside>
        <main>{file ? <><div className="diff-toolbar"><strong title={file.path}>{file.path}</strong><div className="diff-toolbar-actions"><button className={tab === "preview" ? "active" : ""} onClick={() => setTab("preview")}><FileText size={12}/>内容预览</button><button className={tab === "diff" ? "active" : ""} onClick={() => setTab("diff")}><FileDiff size={12}/>Diff</button>{file.status !== "deleted" && changeSet.root && <button onClick={() => onReveal(file.path)}><ExternalLink size={12}/>在目录中显示</button>}</div></div>{tab === "diff" ? <pre className="unified-diff">{(file.diff || "没有可显示的文本差异。\n").split("\n").map((line, index) => <code key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "added" : line.startsWith("-") && !line.startsWith("---") ? "removed" : line.startsWith("@@") ? "hunk" : line.startsWith("---") || line.startsWith("+++") ? "header" : "context"}>{line || " "}</code>)}</pre> : markdown && file.status !== "deleted" ? <article className="rendered-file-preview markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{preview}</ReactMarkdown></article> : <pre className="file-preview">{preview}</pre>}</> : <div className="diff-empty">本轮没有文本文件变化。</div>}</main>
      </div>
      <footer><p>{rolledBack ? "本轮已撤销。" : "预览来自任务完成时的文本快照；若文件后来变化，请在资源管理器中打开最新版本。"}</p><div>{changeSet.root && <button className="open-output-folder" onClick={() => onReveal()}><FolderOpen size={14}/>打开文件夹</button>}<button className="undo-button" disabled={rolledBack || undoing || !changeSet.files.length} onClick={onUndo}><RotateCcw size={14}/>{undoing ? "正在撤销…" : rolledBack ? "已撤销" : "撤销本轮"}</button></div></footer>
    </section>
  </div>;
}
