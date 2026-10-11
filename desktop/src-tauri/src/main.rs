#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::{Emitter, Manager, State};

struct SidecarProcess {
    child: Child,
    stdin: ChildStdin,
}

#[derive(Default)]
struct SidecarState(Mutex<Option<SidecarProcess>>);

fn project_root() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|desktop| desktop.parent())
        .map(PathBuf::from)
        .ok_or_else(|| "无法定位 Python 项目根目录".to_string())
}

#[tauri::command]
fn default_project_path(app: tauri::AppHandle) -> Result<String, String> {
    if cfg!(debug_assertions) {
        return project_root().map(|path| path.to_string_lossy().to_string());
    }
    app.path()
        .document_dir()
        .map(|path| path.to_string_lossy().to_string())
        .map_err(|error| format!("无法定位用户文档目录：{error}"))
}

fn bundled_sidecar_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let path = app.path().resource_dir().ok()?.join("resources").join("astracode-sidecar.exe");
    path.is_file().then_some(path)
}

#[tauri::command]
fn reveal_log_file(path: String) -> Result<(), String> {
    let local = env::var("LOCALAPPDATA").map_err(|_| "无法定位 LOCALAPPDATA".to_string())?;
    let allowed = PathBuf::from(local).join("s_full").join("sessions")
        .canonicalize().map_err(|error| format!("无法定位日志根目录：{error}"))?;
    let target = PathBuf::from(path).canonicalize()
        .map_err(|error| format!("日志文件不存在：{error}"))?;
    if !target.starts_with(&allowed) {
        return Err("拒绝打开应用日志目录以外的路径".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        Command::new("explorer.exe")
            .arg(format!("/select,{}", target.display()))
            .spawn()
            .map_err(|error| format!("无法打开日志文件夹：{error}"))?;
        return Ok(());
    }

    #[cfg(not(target_os = "windows"))]
    {
        let folder = target.parent().unwrap_or(&target);
        Command::new("open")
            .arg(folder)
            .spawn()
            .map_err(|error| format!("无法打开日志文件夹：{error}"))?;
        Ok(())
    }
}

#[tauri::command]
fn reveal_workspace_item(root: String, relative_path: Option<String>) -> Result<(), String> {
    let root = PathBuf::from(root).canonicalize()
        .map_err(|error| format!("项目目录不存在：{error}"))?;
    if !root.is_dir() {
        return Err("项目根路径不是文件夹".to_string());
    }
    let target = if let Some(relative) = relative_path.filter(|value| !value.trim().is_empty()) {
        let candidate = root.join(relative).canonicalize()
            .map_err(|error| format!("生成文件不存在：{error}"))?;
        if !candidate.starts_with(&root) {
            return Err("拒绝打开本次项目目录以外的路径".to_string());
        }
        candidate
    } else {
        root.clone()
    };

    #[cfg(target_os = "windows")]
    {
        let mut command = Command::new("explorer.exe");
        if target.is_file() {
            command.arg(format!("/select,{}", target.display()));
        } else {
            command.arg(&target);
        }
        command.spawn().map_err(|error| format!("无法打开文件夹：{error}"))?;
        return Ok(());
    }

    #[cfg(not(target_os = "windows"))]
    {
        let folder = if target.is_file() { target.parent().unwrap_or(&root) } else { &target };
        Command::new("xdg-open").arg(folder).spawn()
            .map_err(|error| format!("无法打开文件夹：{error}"))?;
        Ok(())
    }
}

#[tauri::command]
fn sidecar_start(
    app: tauri::AppHandle,
    state: State<'_, SidecarState>,
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|_| "sidecar 状态锁已损坏".to_string())?;
    if let Some(process) = guard.as_mut() {
        if process.child.try_wait().map_err(|error| error.to_string())?.is_none() {
            return Ok(());
        }
        *guard = None;
    }

    let mut command = if let Some(sidecar) = bundled_sidecar_path(&app) {
        let runtime = app.path().app_local_data_dir()
            .map_err(|error| format!("无法定位应用数据目录：{error}"))?;
        std::fs::create_dir_all(&runtime).map_err(|error| format!("无法创建应用数据目录：{error}"))?;
        let mut packaged = Command::new(sidecar);
        packaged.current_dir(runtime);
        packaged
    } else {
        let root = project_root()?;
        let python = env::var("S_FULL_PYTHON").unwrap_or_else(|_| "python".to_string());
        let mut development = Command::new(python);
        development.args(["-u", "-m", "agent_harness.sidecar"]).current_dir(root);
        development
    };
    command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    let mut child = command.spawn().map_err(|error| format!("无法启动 Python sidecar：{error}"))?;
    let stdin = child.stdin.take().ok_or_else(|| "无法打开 sidecar 输入".to_string())?;
    let stdout = child.stdout.take().ok_or_else(|| "无法打开 sidecar 输出".to_string())?;
    let stderr = child.stderr.take().ok_or_else(|| "无法打开 sidecar 日志".to_string())?;

    let events = app.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(payload) => {
                    let _ = events.emit("sidecar-event", payload);
                }
                Err(error) => {
                    let _ = events.emit("sidecar-log", format!("读取 sidecar 输出失败：{error}"));
                    break;
                }
            }
        }
        let _ = events.emit("sidecar-exit", ());
    });

    let logs = app;
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let _ = logs.emit("sidecar-log", line);
        }
    });

    *guard = Some(SidecarProcess { child, stdin });
    Ok(())
}

#[tauri::command]
fn sidecar_send(payload: String, state: State<'_, SidecarState>) -> Result<(), String> {
    serde_json::from_str::<serde_json::Value>(&payload)
        .map_err(|error| format!("拒绝发送无效 JSON：{error}"))?;
    let mut guard = state.0.lock().map_err(|_| "sidecar 状态锁已损坏".to_string())?;
    let process = guard.as_mut().ok_or_else(|| "sidecar 尚未启动".to_string())?;
    writeln!(process.stdin, "{payload}").map_err(|error| error.to_string())?;
    process.stdin.flush().map_err(|error| error.to_string())
}

fn stop_process(state: &SidecarState) {
    let Ok(mut guard) = state.0.lock() else {
        return;
    };
    let Some(mut process) = guard.take() else {
        return;
    };
    let _ = writeln!(process.stdin, "{{\"command\":\"shutdown\",\"request_id\":\"desktop-exit\"}}");
    let _ = process.stdin.flush();
    thread::sleep(Duration::from_millis(120));
    if matches!(process.child.try_wait(), Ok(None)) {
        let _ = process.child.kill();
        let _ = process.child.wait();
    }
}

#[tauri::command]
fn sidecar_stop(state: State<'_, SidecarState>) {
    stop_process(&state);
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState::default())
        .invoke_handler(tauri::generate_handler![
            default_project_path,
            reveal_log_file,
            reveal_workspace_item,
            sidecar_start,
            sidecar_send,
            sidecar_stop
        ])
        .build(tauri::generate_context!())
        .expect("failed to build s_full desktop application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            stop_process(&app_handle.state::<SidecarState>());
        }
    });
}
