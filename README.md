[English](README.md) | [简体中文](README.zh-CN.md)

# AstraCode Workbench

**A desktop coding agent for working on local projects with natural language.**

AstraCode brings file operations, command execution, planning, Todo lists, subagents, and multi-agent collaboration into one desktop workbench. Ask it to write code, organize documentation, or run tests—or review a plan before approving implementation. Inspect execution records, file changes, and logs directly in the app.

Current version: **0.8.1**. Primary platform: **Windows 10/11 x64**. Built on `s_full.py` from [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code), retaining upstream mechanisms while adding a modular architecture, desktop interaction, and reliability improvements. See the [product design document](docs/project_docs/product/PRODUCT_DESIGN.md) for feature provenance.

## Install: for users

Open [Releases](https://github.com/1Shuangjiang1/AstraCode/releases) and download:

```text
AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe
AstraCode-Workbench-v0.8.1-Windows-x64-Setup.exe.sha256
```

Use `Setup.exe` to install. GitHub's Source code archives are for developers. If no release is available, follow the source instructions below.

1. Run the installer and open AstraCode.
2. Open Settings in the upper-right corner and enter your own DeepSeek API key.
3. Click `+` in the sidebar to add a project folder, then `+` beside the project to create a conversation.
4. Describe your task and send it. Start with approval-required permissions.
5. Open the beginner guide and tool handbook in the upper-right corner to learn the controls.

The installer includes the Python backend; you do not need Python, Node.js, or Rust to launch it. Commands executed in your projects still require their own runtimes and dependencies, such as Python, Git, or compilers. Initial installation may need internet access to obtain WebView2. The installer is not commercially code-signed, so Windows may show an unknown-publisher warning.

## Run from source: for developers

### Requirements

| Requirement | Purpose |
| --- | --- |
| Windows 10/11 x64 | Primary desktop and command-execution platform |
| Python 3.10+, recommended 3.12 | Agent backend |
| Node.js 22.12+ or 24 LTS, npm | React/Vite frontend |
| Stable Rust, Cargo | Tauri desktop application |
| Visual Studio C++ Build Tools, Windows SDK | Windows compilation dependencies |
| WebView2 Runtime | Desktop WebView |

After downloading or cloning the repository, run these commands in the **repository root**:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Select the Python environment used by the desktop backend.
$env:S_FULL_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path

# Copy the example, then edit .env to enter your own key.
Copy-Item .env.example .env

# Install frontend dependencies on first launch.
.\run_desktop.ps1 -Install
```

For subsequent launches in the same terminal, run `.\run_desktop.ps1`. In a new terminal, set `S_FULL_PYTHON` again or activate `.venv`. After configuring the development environment, you can also double-click `双击启动桌面端.bat`; it uses Python from PATH.

If PowerShell blocks scripts, change the policy for the current process only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Source distributions do not include a frozen sidecar. Development mode launches the Python module; release builds generate and bundle the sidecar.

### Terminal and offline modes

```powershell
.\.venv\Scripts\Activate.ps1
.\run.ps1 -PermissionMode approval

# No real model calls.
.\run.ps1 -Offline
```

The Fake Client checks tool loops and message protocols. Its default responses are simulated; it does not generate code like a real model.

### Browser preview

```powershell
cd desktop
npm ci
npm run dev
```

Visit the address printed in the terminal. The browser uses a demo transport; real tools, approvals, and file operations require the Tauri desktop app.

## Usage

**Project mode:** add a folder and create separate conversations for features, test fixes, or documentation. Conversations work in that folder by default.

**Chat mode:** starts without a working directory, suitable for questions and temporary tasks. Select a directory before file operations; approval mode may require confirmation.

| Composer control | Behavior |
| --- | --- |
| Agent / Plan | Agent executes; Plan investigates read-only and proposes a plan, then waits for approval before implementation |
| Permissions | Safe, approval-required, or full access |
| Quick / High / Max | Controls thinking and reasoning effort, subject to provider support |
| Todo | Requires a 3–7-step checklist and progress updates |
| Verification | Off, standard, or strict; strict verification can inspect read-only and request one targeted repair |
| Templates | Edit requirements in a larger editor before inserting into the composer |
| `/` | Search and load project or built-in skills |
| Send / Stop | Click again during execution to cancel model requests and active commands |

Example prompts:

```text
Create a Python string-decoding function in this project that supports nested brackets.
Save it as decode_string.py, add tests, run them, and report the results and file location.
```

```text
Investigate the project's entry points, dependencies, and tests without changing files.
Propose a refactoring plan and wait for my approval before implementing it.
```

```text
Use Todo to break down this task: organize the README, check launch commands,
and add usage examples. Update Todo after each step and review the final document.
```

```text
Have an Explore subagent find permission-check entry points while the main agent
reads the tests. Summarize potential bypasses. Keep this task read-only.
```

Execution records can be expanded or collapsed. Todo and agent monitors show progress. File cards show additions, modifications, deletions, and line counts, with Markdown/text previews, red/green diffs, folder access, and undo. Enable debug mode to show an Open Log action after a task.

## Features

| Module | Capabilities |
| --- | --- |
| Workbench | Multiple projects and conversations, automatic titles, pin/archive/restore/delete, Markdown, themes, resizable sidebar |
| Agent tool loop | 27 tools, argument validation, permissions, tool results, cancellation, and execution budgets |
| Plan and Todo | Reviewable plans, per-run checklists, enforced Todo mode, live progress |
| Persistent task board | Owners, statuses, dependencies, blocking, and claiming |
| Subagents | Read-only Explore and general-purpose delegation |
| Teammates | Persistent in-session collaboration, message bus, broadcasts, task claiming, idle states, and shutdown |
| Background tasks | Background commands, status queries, completion notifications |
| Skills | `skills/**/SKILL.md`, built-in/project loading, `/` menu |
| Memory | Selection, extraction, indexing, and merging of user / feedback / project / reference memories |
| Context | Old tool-result trimming, offloaded originals, structured summaries, recent-history window |
| Reliability | Tool-message pairing repair, completion evidence checks, optional independent verification, interruption checkpoints |
| Changes | Text snapshots, diffs, previews, conflict-protected undo, failure rollback |
| Diagnostics | JSONL logs, debug controls, tool timeline, multi-agent monitors |
| Testing and release | Fake Client, offline tests, live API suites, Windows installer |

Todo, Memory, Skills, the task board, and core multi-agent mechanisms originate upstream. This project primarily extends modularity, desktop interaction, unified permissions, persistence, and reliability. See the feature-provenance table in the product design document.

## Model configuration

The main model uses the Anthropic Python SDK with DeepSeek's compatible endpoint:

```dotenv
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=your-own-key
S_FULL_MODEL=deepseek-v4-flash
S_FULL_THINKING=1
S_FULL_REASONING_EFFORT=high
```

The implementation maps thinking off to `thinking.type=disabled`; when enabled, it uses `thinking.type=enabled` with `output_config.effort=high/max`. Check endpoint compatibility when changing models: not every model supports these parameters. See [DeepSeek's Anthropic compatibility guide](https://api-docs.deepseek.com/guides/anthropic_api).

Automatic conversation titles have separate, optional configuration:

```dotenv
S_FULL_TITLE_BASE_URL=https://api.siliconflow.cn/v1
S_FULL_TITLE_MODEL=deepseek-ai/DeepSeek-V4-Flash
S_FULL_TITLE_API_KEY=your-own-siliconflow-key
```

If configuration is absent or the request fails, titles fall back to a shortened first message without blocking the main task. Keys from the two providers are not interchangeable.

| Variable | Description |
| --- | --- |
| `S_FULL_PERMISSION_MODE` | Default: `approval`; also `safe` and `full_access` |
| `S_FULL_COMMAND_TIMEOUT` | Per-command timeout, default 30 seconds—not a fixed waiting period |
| `S_FULL_MAX_ROUNDS` | Default: 8; some modes raise the effective minimum |
| `S_FULL_MAX_SECONDS` | Default run budget: 300 seconds |
| `S_FULL_TOKEN_THRESHOLD` | Automatic summarization after roughly 100,000 tokens |
| `S_FULL_FAKE_CLIENT` | Set to `1` for offline model simulation |
| `S_FULL_PYTHON` | Python path for desktop development mode |
| `S_FULL_DATA_DIR` | Root directory for conversation data |

Configuration precedence: process environment variables, user `config.env`, working-directory `.env`, then application-root `.env`. If file edits appear ineffective, check higher-priority settings.

## Data and permissions

Default Windows data locations:

```text
%LOCALAPPDATA%\AstraCode\config.env                          Settings and keys
%LOCALAPPDATA%\s_full\index.sqlite                         Projects, conversations, messages, plans, state
%LOCALAPPDATA%\s_full\sessions\<session-id>\events.jsonl     Conversation events
%LOCALAPPDATA%\s_full\sessions\<session-id>\runs\<id>.jsonl  Per-run logs
%LOCALAPPDATA%\s_full\sessions\<session-id>\runtime\         Memory, task, and team state
```

`s_full` is the retained legacy data-directory name. The CLI saves some state in the working directory by default; override it with `S_FULL_STATE_DIR`. Data is not automatically synced to GitHub. Model requests send relevant messages, file excerpts, and tool results to your configured provider; see [PRIVACY.md](PRIVACY.md).

| Permission mode | Behavior |
| --- | --- |
| safe | Allows read-only/low-risk operations; denies modifications and deletions |
| approval | Usually allows low/medium-risk operations; asks about high-risk operations and blocks critical hazards |
| full_access | No per-operation confirmation within the workspace; path boundaries and critical blocks remain |

An approval can be denied, granted once, or granted for similar operations in the current session. These controls are application-level checks, not an operating-system sandbox.

Shared workspace access is serialized: agents can think concurrently, but file and command access queues behind a shared lock. Separate Git worktrees are not implemented. Background processes and teammate threads cannot reattach across restarts. Summaries may lose details; Memory has no management UI yet; verification does not replace deterministic tests. Undo primarily covers text files, not databases or external side effects. See the [project handoff](docs/project_docs/PROJECT_HANDOFF.md) for boundaries.

## Testing and building

### Offline tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
cd desktop
npm ci
npm run build
cd src-tauri
cargo check
```

pytest isolates the session database and requires no real keys. Historical live-model reports are in [testing](docs/project_docs/testing/); they document acceptance checks on specific dates, not guarantees for every environment.

### Manual live-model tests (billable)

Configure `.env`, then run from the repository root:

```powershell
python -m tests.live_deepseek_crud
python -m tests.live_deepseek_full_suite
python -m tests.live_forced_todo
python -m tests.live_verifier_changes_recovery
```

`live_` scripts are not collected by default pytest discovery. They call real models, create/modify/delete files, and execute commands. Test workspaces are created and cleaned in the system temporary directory by default. Set `S_FULL_TEST_BASE` to an existing test root to override this. Redact new evidence before publishing.

### Build a Windows installer

```powershell
cd desktop
npm ci
cd ..
.\packaging\build_windows.ps1
```

Output goes to `release/`. Builds use an isolated packaging environment and a PyInstaller sidecar. GitHub Actions supports manual builds; pushing a `v*` tag generates Release assets. See the [release guide](docs/project_docs/release/GITHUB_RELEASE_GUIDE.md).

## Repository and documentation

```text
agent_harness/         Agent, tools, permissions, context, Memory, collaboration, persistence
desktop/               React UI and Tauri/Rust bridge
tests/                 Offline and live-model suites
skills/                Built-in skills and scripts
docs/project_docs/     Product, architecture, testing, and release documents
packaging/             Installer builds and public-source export
upstream/, legacy/     Upstream and pre-refactoring snapshots
.github/workflows/     CI and Windows releases
s_full.py              CLI entry point and compatibility layer
```

Recommended reading: [project handoff](docs/project_docs/PROJECT_HANDOFF.md) → [product design](docs/project_docs/product/PRODUCT_DESIGN.md) → [development history](docs/project_docs/product/PRODUCT_DEVELOPMENT.md) → [topic index](docs/project_docs/README.md). These detailed development documents are currently primarily in Chinese.

Public source includes the application, tests, skills, technical documents, and historical code. Personal career materials, personal Memory, runtime databases, keys, caches, and compiled artifacts are excluded. Installers are distributed separately through Releases.

## Troubleshooting

**Double-clicking opens no window?** Source launch requires the full development environment. Run `run_desktop.ps1 -Install` in PowerShell to inspect errors. If you only want to use the app, download the installer.

**Browser shows only demo data?** `npm run dev` previews the UI. Use Tauri to connect to the real agent.

**Why was an operation not approved manually?** Approval mode generally permits low/medium-risk operations automatically and asks for high-risk ones. For read-only tasks, choose safe mode and explicitly request read-only behavior.

**Why did a command time out?** Commands run in non-interactive PowerShell with standard input at EOF. They must not wait for terminal input. Check the actual command, exit code, and duration in the logs.

**How do I report a problem?** Enable debug mode and provide reproduction steps, the version, and redacted log excerpts. Never upload keys, private workspaces, or unchecked complete logs.

## Attribution and license

Licensed under the [MIT License](LICENSE), retaining the upstream `shareAI Lab` copyright. Upstream comparisons are in `upstream/`; pre-refactoring snapshots are in `legacy/`. Dependencies retain their own licenses. See [NOTICE.md](NOTICE.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md).
