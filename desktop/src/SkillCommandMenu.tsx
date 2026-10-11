import { useEffect, useState } from "react";
import { Check, Sparkles } from "lucide-react";
import type { SkillInfo } from "./types";

export function SkillCommandMenu({ skills, query, onSelect, onClose }: { skills: SkillInfo[]; query: string; onSelect: (skill: SkillInfo) => void; onClose: () => void }) {
  const [cursor, setCursor] = useState(0);
  const filtered = skills.filter((skill) => `${skill.name} ${skill.description}`.toLowerCase().includes(query.toLowerCase())).slice(0, 8);
  useEffect(() => { setCursor(0); }, [query]);
  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key === "ArrowDown") { event.preventDefault(); setCursor((value) => Math.min(filtered.length - 1, value + 1)); }
      if (event.key === "ArrowUp") { event.preventDefault(); setCursor((value) => Math.max(0, value - 1)); }
      if (event.key === "Enter" && filtered[cursor]) { event.preventDefault(); onSelect(filtered[cursor]); }
    };
    window.addEventListener("keydown", keys, true); return () => window.removeEventListener("keydown", keys, true);
  }, [cursor, filtered, onClose, onSelect]);
  return <section className="skill-command-menu" aria-label="Skill 命令菜单">
    <header><span><Sparkles size={14}/>可用 Skills</span><small>输入名称筛选 · ↑↓ 选择 · Enter 加载</small></header>
    {filtered.length ? filtered.map((skill, index) => <button type="button" className={index === cursor ? "selected" : ""} key={skill.name} onMouseEnter={() => setCursor(index)} onClick={() => onSelect(skill)}><span><strong>/{skill.name}</strong><small>{skill.description}</small></span>{index === cursor && <Check size={13}/>}</button>) : <div className="skill-empty">没有匹配的 Skill</div>}
  </section>;
}
