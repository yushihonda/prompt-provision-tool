//! PTY-backed external CLI execution (interactive duplex).
//!
//! The pipe-mode runner in `external_cli.rs` / `external_cli_runner.rs`
//! captures stdout/stderr line-by-line — fast and simple but no
//! terminal semantics, so interactive confirmations from `claude`
//! (file edit prompts, dangerous-command confirms, etc.) cannot reach
//! the user.
//!
//! This module spawns the child inside a real PTY using `portable-pty`. The
//! frontend xterm.js terminal becomes a true duplex view: keystrokes
//! flow into the child, and the child's escape sequences render
//! correctly (colors, cursor movement, prompts).
//!
//! State model: each PTY session is keyed by a `session_id` (uuid v4).
//! The frontend gets back the id from `external_cli_pty_spawn` and uses
//! it for write/resize/kill calls.

use parking_lot::Mutex;
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{Read, Write};
use tauri::{AppHandle, Emitter, Manager, State};

const STDOUT_EVENT: &str = "external_cli_pty:stdout";
const EXIT_EVENT: &str = "external_cli_pty:exit";
const READ_BUF_SIZE: usize = 8192;

#[derive(Debug, Clone, Deserialize)]
pub struct PtySpawnRequest {
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    pub cwd: String,
    #[serde(default = "default_cols")]
    pub cols: u16,
    #[serde(default = "default_rows")]
    pub rows: u16,
    #[serde(default)]
    pub env_overrides: HashMap<String, String>,
}

fn default_cols() -> u16 {
    100
}
fn default_rows() -> u16 {
    30
}

#[derive(Debug, Clone, Serialize)]
pub struct PtySpawnResponse {
    pub session_id: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PtyWriteRequest {
    pub session_id: String,
    pub data: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PtyResizeRequest {
    pub session_id: String,
    pub cols: u16,
    pub rows: u16,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PtyKillRequest {
    pub session_id: String,
}

#[derive(Serialize, Clone)]
struct StdoutPayload {
    session_id: String,
    chunk: String,
}

#[derive(Serialize, Clone)]
struct ExitPayload {
    session_id: String,
    exit_code: Option<i32>,
}

/// Active PTY session held in app state.
pub struct PtySession {
    /// Master side of the PTY — used for writes and resize.
    master: Box<dyn portable_pty::MasterPty + Send>,
    /// Writer half (cached so write_session doesn't have to take the master).
    writer: Box<dyn Write + Send>,
    /// Child process handle for kill/wait.
    child: Box<dyn portable_pty::Child + Send + Sync>,
}

#[derive(Default)]
pub struct PtyState {
    sessions: Mutex<HashMap<String, PtySession>>,
}

fn passthrough_env(overrides: &HashMap<String, String>) -> HashMap<String, String> {
    let allow = [
        "HOME", "PATH", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TERM",
        "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
        "ANTHROPIC_CONFIG_DIR",
    ];
    let mut env: HashMap<String, String> = HashMap::new();
    for k in allow {
        if let Ok(v) = std::env::var(k) {
            env.insert(k.to_string(), v);
        }
    }
    env.insert("TERM".into(), "xterm-256color".into());
    for (k, v) in overrides {
        env.insert(k.clone(), v.clone());
    }
    env
}

fn validate_cwd(cwd_str: &str) -> Result<std::path::PathBuf, String> {
    let path = std::path::PathBuf::from(cwd_str);
    if !path.is_absolute() {
        return Err("cwd_must_be_absolute".into());
    }
    if !path.exists() {
        return Err("cwd_does_not_exist".into());
    }
    if !path.is_dir() {
        return Err("cwd_not_a_directory".into());
    }
    if let Some(home) = std::env::var_os("HOME").map(std::path::PathBuf::from) {
        if !path.starts_with(&home) {
            return Err("cwd_outside_home".into());
        }
    }
    Ok(path)
}

#[tauri::command]
pub async fn external_cli_pty_spawn(
    app: AppHandle,
    state: State<'_, PtyState>,
    req: PtySpawnRequest,
) -> Result<PtySpawnResponse, String> {
    let cwd = validate_cwd(&req.cwd)?;
    let cols = req.cols.max(20);
    let rows = req.rows.max(5);

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| format!("openpty_failed: {e}"))?;

    let mut cmd = CommandBuilder::new(&req.command);
    for a in &req.args {
        cmd.arg(a);
    }
    cmd.cwd(cwd);
    // portable-pty inherits parent env unless we clear it; we want a controlled env.
    for (k, v) in passthrough_env(&req.env_overrides) {
        cmd.env(k, v);
    }

    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| format!("spawn_failed: {e}"))?;

    // Drop the slave on the parent side to let the child own it.
    drop(pair.slave);

    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| format!("clone_reader_failed: {e}"))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| format!("take_writer_failed: {e}"))?;

    let session_id = uuid::Uuid::new_v4().to_string();
    let session_id_for_reader = session_id.clone();
    let session_id_for_waiter = session_id.clone();
    let app_for_reader = app.clone();
    let app_for_waiter = app.clone();

    // Insert the session BEFORE we start the reader thread so writes are valid immediately.
    state.sessions.lock().insert(
        session_id.clone(),
        PtySession {
            master: pair.master,
            writer,
            child,
        },
    );

    // Reader thread: blocking read on the master PTY → emit chunks.
    std::thread::spawn(move || {
        let mut buf = [0u8; READ_BUF_SIZE];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let chunk = String::from_utf8_lossy(&buf[..n]).into_owned();
                    let _ = app_for_reader.emit(
                        STDOUT_EVENT,
                        StdoutPayload {
                            session_id: session_id_for_reader.clone(),
                            chunk,
                        },
                    );
                }
                Err(_) => break,
            }
        }
    });

    // Waiter thread: wait for child exit, emit exit event, drop session.
    std::thread::spawn(move || {
        // Wait inside a short loop because portable_pty::Child::wait takes &mut self
        // and we don't keep the child outside the state map. So we poll try_wait
        // through the state map.
        loop {
            std::thread::sleep(std::time::Duration::from_millis(200));
            let exit_code = {
                let state: tauri::State<PtyState> = app_for_waiter.state();
                let mut sessions = state.sessions.lock();
                let Some(session) = sessions.get_mut(&session_id_for_waiter) else {
                    return; // killed/cleaned up
                };
                match session.child.try_wait() {
                    Ok(Some(status)) => Some(status.exit_code() as i32),
                    Ok(None) => continue,
                    Err(_) => Some(-1),
                }
            };
            // Drop the session entry now that the child has exited.
            {
                let state: tauri::State<PtyState> = app_for_waiter.state();
                state.sessions.lock().remove(&session_id_for_waiter);
            }
            let _ = app_for_waiter.emit(
                EXIT_EVENT,
                ExitPayload {
                    session_id: session_id_for_waiter.clone(),
                    exit_code,
                },
            );
            break;
        }
    });

    Ok(PtySpawnResponse { session_id })
}

#[tauri::command]
pub async fn external_cli_pty_write(
    state: State<'_, PtyState>,
    req: PtyWriteRequest,
) -> Result<(), String> {
    let mut sessions = state.sessions.lock();
    let session = sessions
        .get_mut(&req.session_id)
        .ok_or_else(|| "session_not_found".to_string())?;
    session
        .writer
        .write_all(req.data.as_bytes())
        .map_err(|e| format!("write_failed: {e}"))?;
    session
        .writer
        .flush()
        .map_err(|e| format!("flush_failed: {e}"))?;
    Ok(())
}

#[tauri::command]
pub async fn external_cli_pty_resize(
    state: State<'_, PtyState>,
    req: PtyResizeRequest,
) -> Result<(), String> {
    let sessions = state.sessions.lock();
    let session = sessions
        .get(&req.session_id)
        .ok_or_else(|| "session_not_found".to_string())?;
    session
        .master
        .resize(PtySize {
            rows: req.rows.max(5),
            cols: req.cols.max(20),
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| format!("resize_failed: {e}"))?;
    Ok(())
}

#[tauri::command]
pub async fn external_cli_pty_kill(
    state: State<'_, PtyState>,
    req: PtyKillRequest,
) -> Result<(), String> {
    let mut sessions = state.sessions.lock();
    let session = sessions
        .get_mut(&req.session_id)
        .ok_or_else(|| "session_not_found".to_string())?;
    session
        .child
        .kill()
        .map_err(|e| format!("kill_failed: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validate_cwd_rejects_relative() {
        assert!(validate_cwd("relative/path").is_err());
    }

    #[test]
    fn validate_cwd_rejects_outside_home() {
        assert!(validate_cwd("/etc").is_err());
    }

    #[test]
    fn passthrough_env_includes_term() {
        let env = passthrough_env(&HashMap::new());
        assert_eq!(env.get("TERM").map(String::as_str), Some("xterm-256color"));
    }
}
