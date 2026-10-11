"""Export a reviewed source allowlist; never export local runtime or credentials.

Usage: python packaging/export_public.py [--output PATH]
Writes a fresh AstraCode directory and zip; refuses to overwrite existing output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = {
    "README.md", "README.zh-CN.md", "LICENSE", "NOTICE.md", "CONTRIBUTING.md", "SECURITY.md", "PRIVACY.md",
    "AGENTS.md", ".gitignore", ".env.example", "requirements.txt", "requirements-dev.txt",
    "requirements-release.txt", "s_full.py", "run.ps1", "run_tests.ps1", "run_desktop.ps1",
    "双击启动桌面端.bat",
}
TREES = {"agent_harness", "tests", "skills", "upstream", "legacy"}
DESKTOP_FILES = {
    "README.md", "index.html", "app-icon.svg", "package.json", "package-lock.json",
    "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts",
    "src-tauri/Cargo.toml", "src-tauri/Cargo.lock", "src-tauri/build.rs",
    "src-tauri/tauri.conf.json",
}
EXCLUDED_PARTS = {
    "__pycache__", "node_modules", "target", "dist", "build", ".git", ".pytest_cache",
    ".memory", ".tasks", ".team", ".transcripts", ".venv", "career",
}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".lock", ".yml", ".yaml", ".ps1", ".bat", ".ts", ".tsx", ".css", ".html", ".svg"}
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\b(?:ghp_|github_pat_|gho_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def permitted(relative: Path) -> bool:
    parts = relative.parts
    if any(part in EXCLUDED_PARTS for part in parts):
        return False
    if relative.suffix.lower() in {".pyc", ".pyo", ".log", ".exe", ".dll", ".sqlite"}:
        return False
    name = relative.as_posix()
    if len(parts) == 1:
        return name in ROOT_FILES
    if parts[0] in TREES:
        return relative.suffix.lower() in TEXT_SUFFIXES or relative.name == "LICENSE"
    if parts[0] == "desktop":
        tail = Path(*parts[1:]).as_posix()
        return tail in DESKTOP_FILES or tail.startswith(("src/", "src-tauri/src/", "src-tauri/icons/", "src-tauri/capabilities/"))
    if name.startswith("docs/project_docs/"):
        # Historical evidence is JSON summaries, never raw private screenshots/logs.
        return relative.suffix.lower() in {".md", ".json"}
    if parts[0] == "packaging":
        return len(parts) == 2 and relative.suffix.lower() in {".py", ".ps1"}
    return name.startswith(".github/") and relative.suffix.lower() in TEXT_SUFFIXES


def public_text(relative: Path, text: str) -> str:
    if relative.as_posix().startswith("docs/"):
        # Redact personal machine paths in historical docs/evidence, not executable code.
        text = re.sub(r"[CD]:[\\/]+cbl_file[^\s`\"'<>|)；，]*", "<LOCAL_PROJECT>", text, flags=re.I)
        text = re.sub(r"C:[\\/]+Users[\\/]+[^\\/\s`\"']+", "<USER_HOME>", text, flags=re.I)
        text = re.sub(r"D:[\\/]+baidu", "<TEST_ROOT>", text, flags=re.I)
        # Remove references to excluded personal-career documents.
        text = "\n".join(line for line in text.splitlines() if "career/" not in line and "AI_EXPLAINER_HANDOFF" not in line)
        if relative.name == "README.md":
            text = re.sub(r"## career：求职材料[\s\S]*?(?=## 维护规则)", "", text)
        text += "\n"
    return text


def scan(output: Path) -> list[str]:
    issues = []
    for path in output.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(output)
        if path.name.startswith(".env") and path.name != ".env.example":
            issues.append(f"forbidden config: {relative}")
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", ".env.example", ".gitignore"}:
            text = path.read_text(encoding="utf-8-sig")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                issues.append(f"possible credential: {relative}")
            if path.suffix == ".json":
                try:
                    json.loads(text)
                except ValueError:
                    issues.append(f"invalid JSON: {relative}")
            if path.suffix == ".md":
                # Check file links; heading anchors are validated by the reader.
                for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
                    target = match.group(1).strip("<>").split("#", 1)[0]
                    if not target or re.match(r"(?:https?://|mailto:|data:)", target):
                        continue
                    if not (path.parent / target).exists():
                        issues.append(f"broken link: {relative} -> {target}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT.parent / "public_exports" / datetime.now().strftime("AstraCode-%Y%m%d-%H%M%S")).resolve()
    if output.exists():
        parser.error("Output already exists; use a new directory.")
    output.mkdir(parents=True)
    source_files = []
    for folder, directories, names in os.walk(ROOT, followlinks=False):
        directories[:] = [name for name in directories if name not in EXCLUDED_PARTS
                          and not (Path(folder) / name).is_symlink()
                          and (Path(folder) != ROOT or name in TREES | {"desktop", "docs", "packaging", ".github"})]
        source_files.extend(Path(folder) / name for name in names)
    for path in source_files:
        relative = path.relative_to(ROOT)
        if path.is_symlink() or not path.is_file() or not permitted(relative):
            continue
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", ".env.example", ".gitignore"}:
            target.write_text(public_text(relative, path.read_text(encoding="utf-8-sig")), encoding="utf-8")
        else:
            shutil.copy2(path, target)
    issues = scan(output)
    if issues:
        print(json.dumps({"output": str(output), "issues": issues}, ensure_ascii=False, indent=2))
        return 1
    files = [path for path in sorted(output.rglob("*")) if path.is_file()]
    manifest = {"source_version": "0.8.1", "files": [
        {"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files
    ], "excluded": ["credentials", "runtime data", "career materials", "dependencies", "build artifacts", "personal screenshots"],
        "checks": {"credential_patterns": "passed", "json": "passed", "relative_links": "passed"}}
    (output / "PUBLIC_SOURCE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = Path(str(output) + ".zip")
    if archive.exists():
        raise RuntimeError("Archive already exists; no overwrite allowed.")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, Path("AstraCode") / path.relative_to(output))
    print(json.dumps({"output": str(output), "archive": str(archive), "files": len(files) + 1,
                      "archive_bytes": archive.stat().st_size, "checks": manifest["checks"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
