import { useEffect, useState } from "react";
import { Check, ChevronLeft, ChevronRight, FileDiff, FileText, FolderOpen, Play, Send, Settings, Sparkles, X } from "lucide-react";

interface OnboardingGuideProps { open: boolean; onClose: () => void; onOpenSettings: () => void; }
type GuideSceneName = "setup" | "task" | "controls" | "progress" | "files";

const steps: Array<{ scene: GuideSceneName; kicker: string; title: string; body: string; prompt?: string; callout: string; hint: string; points: string[] }> = [
  {
    scene: "setup", kicker: "01 · FIRST LAUNCH", title: "先配置模型，再添加项目",
    body: "第一次使用时，先点右上角设置填写自己的 DeepSeek API Key。然后使用左侧项目栏顶部的 + 选择工作文件夹；Key 只保存在你的电脑上。",
    callout: "从这里开始", hint: "设置连接模型，左侧 + 添加项目目录",
    points: ["项目模式：文件操作默认限制在当前项目中", "纯聊天：可以先聊天，需要操作文件时再选择目录", "第一次使用建议保持“需要审批”，更容易看清 Agent 要做什么"],
  },
  {
    scene: "task", kicker: "02 · FIRST TASK", title: "在输入框里交代完整任务",
    body: "把 Agent 当作一位刚加入项目的同事：说明要改什么、不能动什么，以及怎样才算完成。描述越具体，返工越少。",
    prompt: "请在当前项目创建 hello.py，输出 Hello AstraCode；运行它确认结果，并告诉我修改了哪些文件。",
    callout: "主要输入区", hint: "输入目标、范围和验收条件，再点击发送",
    points: ["Ctrl + Enter 可以快速发送", "运行中发送按钮会变成“停止任务”，再次点击即可终止", "聊天内容支持 Markdown，代码、表格和列表会自动排版"],
  },
  {
    scene: "controls", kicker: "03 · TASK CONTROLS", title: "发送前，选择这次任务怎么做",
    body: "输入框下方是一排任务控制项。简单任务保持默认即可；复杂修改可以先 Plan、打开 Todo，并提高验证强度。",
    callout: "任务控制栏", hint: "模板、Todo、模式、权限、思考和验证都在这里",
    points: ["Agent 直接执行；Plan 先调查并给计划，批准后才执行", "Todo 强制拆成 3–7 步并逐项更新", "权限分为安全、需要审批和完全访问", "输入 / 可选择 Skill；模板按钮提供可编辑的任务范本"],
  },
  {
    scene: "progress", kicker: "04 · WATCH PROGRESS", title: "运行中，随时查看它进行到哪里",
    body: "执行记录展示模型和工具的实际动作；右侧概览会同步 Todo、子 Agent、Teammate、计划和验证状态。这里比只看最后一句回复更可靠。",
    callout: "实时进度", hint: "Todo、协作 Agent 和任务状态集中显示",
    points: ["执行记录可以展开或收起", "Todo 当前步骤会高亮，完成项会自动划去", "打开调试模式后，任务结束处会出现日志入口", "审批请求会说明执行者、工具、风险和具体参数"],
  },
  {
    scene: "files", kicker: "05 · REVIEW FILES", title: "最后检查文件，再决定保留或撤销",
    body: "只要本轮新增、修改或删除了文本文件，回复下方就会出现文件卡片。你可以直接阅读 Markdown、查看红绿 Diff，或打开文件所在目录。",
    callout: "本轮文件", hint: "预览内容、查看 Diff、打开目录或撤销修改",
    points: ["绿色表示新增内容，红色表示删除内容", "Markdown 默认按文档样式渲染，也能切换到原始 Diff", "撤销只恢复本轮记录的文本修改，不会覆盖任务后的手动改动", "严格验证适合重要代码；简单问答可以关闭额外验证"],
  },
];

function GuideScene({ scene, callout, hint }: { scene: GuideSceneName; callout: string; hint: string }) {
  return <div className={`guide-scene scene-${scene}`} aria-label={`${callout}：${hint}`}>
    <div className="guide-mock-window" aria-hidden="true">
      <div className="guide-mock-top"><i>A</i><b>AstraCode</b><span>当前项目</span><em/><Settings size={10}/></div>
      <aside className="guide-mock-rail"><div className="mock-mode">项目　聊天</div><div className="mock-project-add"><b>项目</b><span>＋</span></div><div className="mock-project">示例项目</div><div className="mock-thread">实现登录页面</div><div className="mock-thread muted">修复单元测试</div></aside>
      <section className="guide-mock-main"><div className="mock-message"><i/><span><b>AstraCode</b><small>告诉我你想完成什么。</small></span></div><div className="mock-message user"><i/><span><b>你</b><small>请实现一个清晰、可测试的功能……</small></span></div>{scene === "files" && <div className="mock-file-card"><div><FileText size={11}/><b>2 个本轮文件</b></div><span><FileDiff size={9}/>查看 Diff</span><span><FolderOpen size={9}/>打开目录</span></div>}<div className="mock-composer-box"><span>描述任务；输入 / 选择 Skill…</span><div className="mock-control-strip"><i>模板</i><i>Todo</i><i>Agent</i><i>审批</i><i>High</i></div><button><Send size={9}/></button></div></section>
      <aside className="guide-mock-inspector"><b>运行概览</b><div><span>状态</span><strong>进行中</strong></div><div><span>Todo</span><strong>2 / 4</strong></div><div className="mock-progress"><i/></div><small>● 检查项目结构</small><small>◌ 修改文件</small><small>◌ 运行验证</small></aside>
    </div>
    <div className="guide-focus-ring" aria-hidden="true"/>
    <div className="guide-callout"><b>{callout}</b><span>{hint}</span></div>
  </div>;
}

export function OnboardingGuide({ open, onClose, onOpenSettings }: OnboardingGuideProps) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!open) return;
    setStep(0);
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open, onClose]);
  if (!open) return null;
  const current = steps[step];
  return <div className="modal-layer onboarding-layer" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="onboarding-dialog" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
      <header><div className="onboarding-brand"><Sparkles size={17}/></div><div><p className="eyebrow">ASTRACODE QUICKSTART</p><h2 id="onboarding-title">新手使用指南</h2></div><button className="icon-button" aria-label="关闭新手指南" onClick={onClose}><X size={16}/></button></header>
      <div className="onboarding-progress" aria-label={`第 ${step + 1} 步，共 ${steps.length} 步`}>{steps.map((item, index) => <button key={item.kicker} className={index === step ? "active" : index < step ? "done" : ""} onClick={() => setStep(index)} aria-label={`查看第 ${index + 1} 步`}><i/>{index < step ? <Check size={11}/> : index + 1}</button>)}</div>
      <main><GuideScene scene={current.scene} callout={current.callout} hint={current.hint}/><article><div><small>{current.kicker}</small><h3>{current.title}</h3><p>{current.body}</p></div>{current.prompt && <div className="starter-prompt"><span>可以直接试试</span><code>{current.prompt}</code></div>}<ul>{current.points.map((point) => <li key={point}><Check size={13}/><span>{point}</span></li>)}</ul></article></main>
      <footer><button disabled={step === 0} onClick={() => setStep((value) => value - 1)}><ChevronLeft size={14}/>上一步</button><div><span>{step + 1}</span> / {steps.length}</div>{step < steps.length - 1 ? <button className="guide-next" onClick={() => setStep((value) => value + 1)}>下一步<ChevronRight size={14}/></button> : <button className="guide-next" onClick={() => { onClose(); onOpenSettings(); }}><Play size={13} fill="currentColor"/>打开设置，开始使用</button>}</footer>
    </section>
  </div>;
}
