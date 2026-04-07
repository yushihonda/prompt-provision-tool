//! Generic runner for `ExternalCliAdapter` instances.
//!
//! Owns runtime-agnostic concerns:
//! - cwd validation
//! - subprocess spawn (pipe mode — PTY mode lives in `external_cli_pty.rs`)
//! - line-buffered stdout/stderr capture with event streaming
//! - timeout enforcement
//! - changed-file diff
//! - output truncation
//! - emission of unified `external_cli:*` events
//!
//! Concrete adapters provide command construction, prompt wrapping,
//! failure classification, and result normalization.

use serde::Serialize;
use std::collections::HashSet;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

use crate::external_cli_registry::ExternalCliRegistry;
use crate::external_cli_traits::{
    ExternalCliCapability, ExternalCliExecutionRequest, ExternalCliExecutionResult,
    ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
const PLANNED_EVENT: &str = "external_cli:planned";
const CAPABILITY_EVENT: &str = "external_cli:capability_checked";
const STARTED_EVENT: &str = "external_cli:started";
const STDOUT_EVENT: &str = "external_cli:stdout_chunk";
const STDERR_EVENT: &str = "external_cli:stderr_chunk";
const FINISHED_EVENT: &str = "external_cli:finished";
const FAILED_EVENT: &str = "external_cli:failed";

// ───────────────────────────────────────────────
// helpers
// ───────────────────────────────────────────────

pub fn truncate_output(s: &str, max_bytes: usize) -> (String, bool) {
    if s.len() <= max_bytes {
        (s.to_string(), false)
    } else {
        let mut cut = max_bytes;
        while cut > 0 && !s.is_char_boundary(cut) {
            cut -= 1;
        }
        (s[..cut].to_string(), true)
    }
}

pub fn build_command_line_preview(command: &str, args: &[String]) -> String {
    let mut parts: Vec<String> = vec![command.to_string()];
    for a in args {
        parts.push(quote_arg(a));
    }
    let line = parts.join(" ");
    if line.len() > 400 {
        format!("{}...", &line[..400])
    } else {
        line
    }
}

fn quote_arg(s: &str) -> String {
    if s.chars()
        .all(|c| c.is_ascii_alphanumeric() || "-_./=:".contains(c))
    {
        s.to_string()
    } else {
        format!("\"{}\"", s.replace('"', "\\\""))
    }
}

pub fn snapshot_top_level(cwd: &Path) -> HashSet<PathBuf> {
    let mut out = HashSet::new();
    if let Ok(entries) = std::fs::read_dir(cwd) {
        for e in entries.flatten() {
            out.insert(e.path());
        }
    }
    out
}

pub fn diff_changed_files(cwd: &Path, before: &HashSet<PathBuf>) -> Vec<String> {
    let mut changed: Vec<String> = vec![];
    if let Ok(entries) = std::fs::read_dir(cwd) {
        for e in entries.flatten() {
            let p = e.path();
            if !before.contains(&p) {
                if let Ok(rel) = p.strip_prefix(cwd) {
                    changed.push(rel.to_string_lossy().into_owned());
                }
            }
        }
    }
    changed.sort();
    changed
}

pub fn validate_cwd(cwd_str: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(cwd_str);
    if !path.is_absolute() {
        return Err("cwd_must_be_absolute".into());
    }
    if !path.exists() {
        return Err("cwd_does_not_exist".into());
    }
    if !path.is_dir() {
        return Err("cwd_not_a_directory".into());
    }
    if let Some(home) = std::env::var_os("HOME").map(PathBuf::from) {
        if !path.starts_with(&home) {
            return Err("cwd_outside_home".into());
        }
    }
    Ok(path)
}

pub fn passthrough_env(
    allow: &[String],
    overrides: &std::collections::HashMap<String, String>,
) -> std::collections::HashMap<String, String> {
    let mut env = std::collections::HashMap::new();
    for k in allow {
        if let Ok(v) = std::env::var(k) {
            env.insert(k.clone(), v);
        }
    }
    for (k, v) in overrides {
        env.insert(k.clone(), v.clone());
    }
    env
}

fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339()
}

// ───────────────────────────────────────────────
// event payloads
// ───────────────────────────────────────────────

#[derive(Serialize, Clone)]
struct PlannedPayload<'a> {
    task_id: &'a str,
    workflow_run_id: &'a str,
    adapter_id: &'a str,
    runtime: &'a str,
    cwd: &'a str,
    required_capabilities: Vec<&'a str>,
}

#[derive(Serialize, Clone)]
struct CapabilityPayload<'a> {
    task_id: &'a str,
    workflow_run_id: &'a str,
    adapter_id: &'a str,
    runtime: &'a str,
    passed: bool,
    missing_capabilities: Vec<&'a str>,
}

#[derive(Serialize, Clone)]
struct StartedPayload<'a> {
    task_id: &'a str,
    workflow_run_id: &'a str,
    adapter_id: &'a str,
    runtime: &'a str,
    cwd: &'a str,
    command_preview: &'a str,
    started_at: &'a str,
}

#[derive(Serialize, Clone)]
struct ChunkPayload {
    task_id: String,
    workflow_run_id: String,
    adapter_id: String,
    runtime: String,
    transport: String,
    seq: u64,
    chunk: String,
}

#[derive(Serialize, Clone)]
struct FinishedPayload<'a> {
    task_id: &'a str,
    workflow_run_id: &'a str,
    adapter_id: &'a str,
    runtime: &'a str,
    status: &'a str,
    exit_code: Option<i32>,
    duration_ms: u64,
    stdout_truncated: bool,
    stderr_truncated: bool,
    changed_files_count: usize,
}

#[derive(Serialize, Clone)]
struct FailedPayload<'a> {
    task_id: &'a str,
    workflow_run_id: &'a str,
    adapter_id: &'a str,
    runtime: &'a str,
    status: &'a str,
    reason: &'a str,
}

fn emit<T: Serialize + Clone>(app: &AppHandle, event: &str, payload: T) {
    let _ = app.emit(event, payload);
}

// ───────────────────────────────────────────────
// streaming
// ───────────────────────────────────────────────

async fn stream_lines<R: tokio::io::AsyncRead + Unpin + Send + 'static>(
    reader: R,
    app: AppHandle,
    task_id: String,
    workflow_run_id: String,
    adapter_id: String,
    runtime: String,
    seq_counter: Arc<AtomicU64>,
    event_name: &'static str,
) -> String {
    let mut buf = BufReader::new(reader);
    let mut line = String::new();
    let mut accumulated = String::new();
    loop {
        line.clear();
        match buf.read_line(&mut line).await {
            Ok(0) => break,
            Ok(_) => {
                if accumulated.len() < MAX_OUTPUT_BYTES * 2 {
                    accumulated.push_str(&line);
                }
                let seq = seq_counter.fetch_add(1, Ordering::Relaxed);
                emit(
                    &app,
                    event_name,
                    ChunkPayload {
                        task_id: task_id.clone(),
                        workflow_run_id: workflow_run_id.clone(),
                        adapter_id: adapter_id.clone(),
                        runtime: runtime.clone(),
                        transport: "pipe".into(),
                        seq,
                        chunk: line.clone(),
                    },
                );
            }
            Err(_) => break,
        }
    }
    accumulated
}

// ───────────────────────────────────────────────
// generic runner
// ───────────────────────────────────────────────

pub async fn run_external_cli_with_adapter(
    registry: &ExternalCliRegistry,
    app: AppHandle,
    req: ExternalCliExecutionRequest,
    cancel: Arc<AtomicBool>,
) -> ExternalCliExecutionResult {
    let started_at = now_iso();
    let started_instant = Instant::now();
    let runtime_str = req.runtime.as_str();
    let required_caps_str: Vec<&str> =
        req.required_capabilities.iter().map(|c| c.as_str()).collect();

    emit(
        &app,
        PLANNED_EVENT,
        PlannedPayload {
            task_id: &req.task_id,
            workflow_run_id: &req.workflow_run_id,
            adapter_id: &req.adapter_id,
            runtime: runtime_str,
            cwd: &req.cwd,
            required_capabilities: required_caps_str.clone(),
        },
    );

    // 1. registry lookup
    let adapter = match registry.get(&req.adapter_id) {
        Some(a) => a,
        None => {
            let reason = format!("adapter_not_found: {}", req.adapter_id);
            emit(
                &app,
                FAILED_EVENT,
                FailedPayload {
                    task_id: &req.task_id,
                    workflow_run_id: &req.workflow_run_id,
                    adapter_id: &req.adapter_id,
                    runtime: runtime_str,
                    status: ExternalCliExecutionStatus::Unsupported.as_str(),
                    reason: &reason,
                },
            );
            return error_result(
                &req,
                ExternalCliExecutionStatus::Unsupported,
                started_at,
                String::new(),
                reason,
                String::new(),
                false,
            );
        }
    };
    let cfg = adapter.adapter_config();

    // 2. environment validation
    if let Err(reason) = adapter.validate_environment() {
        let status = ExternalCliExecutionStatus::MissingBinary;
        emit(
            &app,
            FAILED_EVENT,
            FailedPayload {
                task_id: &req.task_id,
                workflow_run_id: &req.workflow_run_id,
                adapter_id: &cfg.adapter_id,
                runtime: runtime_str,
                status: status.as_str(),
                reason: &reason,
            },
        );
        return error_result(
            &req,
            status,
            started_at,
            String::new(),
            reason,
            String::new(),
            false,
        );
    }

    // 3. capability check
    let cap_check = adapter.supports_capabilities(&req.required_capabilities);
    let (cap_passed, missing_caps): (bool, Vec<ExternalCliCapability>) = match cap_check {
        Ok(()) => (true, vec![]),
        Err(missing) => (false, missing),
    };
    let missing_str: Vec<&str> = missing_caps.iter().map(|c| c.as_str()).collect();
    emit(
        &app,
        CAPABILITY_EVENT,
        CapabilityPayload {
            task_id: &req.task_id,
            workflow_run_id: &req.workflow_run_id,
            adapter_id: &cfg.adapter_id,
            runtime: runtime_str,
            passed: cap_passed,
            missing_capabilities: missing_str.clone(),
        },
    );
    if !cap_passed {
        let reason = format!(
            "capability_mismatch: missing {:?}",
            missing_caps
                .iter()
                .map(|c| c.as_str())
                .collect::<Vec<_>>()
        );
        emit(
            &app,
            FAILED_EVENT,
            FailedPayload {
                task_id: &req.task_id,
                workflow_run_id: &req.workflow_run_id,
                adapter_id: &cfg.adapter_id,
                runtime: runtime_str,
                status: ExternalCliExecutionStatus::CapabilityMismatch.as_str(),
                reason: &reason,
            },
        );
        return error_result(
            &req,
            ExternalCliExecutionStatus::CapabilityMismatch,
            started_at,
            String::new(),
            reason,
            String::new(),
            false,
        );
    }

    // 4. cwd
    let cwd = match validate_cwd(&req.cwd) {
        Ok(p) => p,
        Err(reason) => {
            emit(
                &app,
                FAILED_EVENT,
                FailedPayload {
                    task_id: &req.task_id,
                    workflow_run_id: &req.workflow_run_id,
                    adapter_id: &cfg.adapter_id,
                    runtime: runtime_str,
                    status: ExternalCliExecutionStatus::Failed.as_str(),
                    reason: &reason,
                },
            );
            return error_result(
                &req,
                ExternalCliExecutionStatus::Failed,
                started_at,
                String::new(),
                reason,
                String::new(),
                cap_passed,
            );
        }
    };

    // 5. command + prompt
    let prompt = match adapter.build_prompt(&req) {
        Ok(p) => p,
        Err(e) => {
            return error_result(
                &req,
                ExternalCliExecutionStatus::Failed,
                started_at,
                String::new(),
                format!("prompt_build_failed: {e}"),
                String::new(),
                cap_passed,
            );
        }
    };
    // Inject the rendered prompt into the request before asking the
    // adapter to build args; some adapters read from req.prompt directly.
    let mut effective_req = req.clone();
    effective_req.prompt = prompt;
    let (command, args) = match adapter.build_command(&effective_req) {
        Ok(x) => x,
        Err(e) => {
            return error_result(
                &req,
                ExternalCliExecutionStatus::Failed,
                started_at,
                String::new(),
                format!("command_build_failed: {e}"),
                String::new(),
                cap_passed,
            );
        }
    };
    let preview = build_command_line_preview(&command, &args);

    // 6. snapshot files
    let started_files = snapshot_top_level(&cwd);

    // 7. spawn
    let mut cmd = Command::new(&command);
    cmd.args(&args)
        .current_dir(&cwd)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .stdin(std::process::Stdio::null());
    cmd.env_clear();
    for (k, v) in passthrough_env(&cfg.env_keys_passthrough, &req.env_overrides) {
        cmd.env(k, v);
    }

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            let status = adapter.classify_failure(None, "", "", Some(e.kind()));
            let reason = format!("{}: {}", status.as_str(), e);
            emit(
                &app,
                FAILED_EVENT,
                FailedPayload {
                    task_id: &req.task_id,
                    workflow_run_id: &req.workflow_run_id,
                    adapter_id: &cfg.adapter_id,
                    runtime: runtime_str,
                    status: status.as_str(),
                    reason: &reason,
                },
            );
            return error_result(
                &req,
                status,
                started_at,
                String::new(),
                reason,
                preview,
                cap_passed,
            );
        }
    };

    emit(
        &app,
        STARTED_EVENT,
        StartedPayload {
            task_id: &req.task_id,
            workflow_run_id: &req.workflow_run_id,
            adapter_id: &cfg.adapter_id,
            runtime: runtime_str,
            cwd: &req.cwd,
            command_preview: &preview,
            started_at: &started_at,
        },
    );

    let stdout = child.stdout.take().expect("piped stdout");
    let stderr = child.stderr.take().expect("piped stderr");
    let seq_counter = Arc::new(AtomicU64::new(0));

    let stdout_handle = tokio::spawn(stream_lines(
        stdout,
        app.clone(),
        req.task_id.clone(),
        req.workflow_run_id.clone(),
        cfg.adapter_id.clone(),
        runtime_str.to_string(),
        seq_counter.clone(),
        STDOUT_EVENT,
    ));
    let stderr_handle = tokio::spawn(stream_lines(
        stderr,
        app.clone(),
        req.task_id.clone(),
        req.workflow_run_id.clone(),
        cfg.adapter_id.clone(),
        runtime_str.to_string(),
        seq_counter.clone(),
        STDERR_EVENT,
    ));

    let timeout = Duration::from_millis(req.timeout_ms.max(1));
    let wait_result = tokio::time::timeout(timeout, child.wait()).await;

    let mut interim_status = ExternalCliExecutionStatus::Pending;
    let mut exit_code: Option<i32> = None;
    match wait_result {
        Ok(Ok(es)) => {
            exit_code = es.code();
            if cancel.load(Ordering::Relaxed) {
                interim_status = ExternalCliExecutionStatus::Cancelled;
            }
        }
        Ok(Err(e)) => {
            let _ = child.start_kill();
            let reason = format!("wait_failed: {e}");
            return error_result(
                &req,
                ExternalCliExecutionStatus::Failed,
                started_at,
                String::new(),
                reason,
                preview,
                cap_passed,
            );
        }
        Err(_) => {
            let _ = child.start_kill();
            interim_status = ExternalCliExecutionStatus::TimedOut;
        }
    }

    let stdout_text = stdout_handle.await.unwrap_or_default();
    let stderr_text = stderr_handle.await.unwrap_or_default();
    let (stdout_trunc, stdout_truncated) = truncate_output(&stdout_text, MAX_OUTPUT_BYTES);
    let (stderr_trunc, stderr_truncated) = truncate_output(&stderr_text, MAX_OUTPUT_BYTES);
    let changed_files = diff_changed_files(&cwd, &started_files);
    let duration_ms = started_instant.elapsed().as_millis() as u64;
    let finished_at = now_iso();

    let mut result = adapter.normalize_result(
        &effective_req,
        stdout_trunc,
        stderr_trunc,
        exit_code,
        duration_ms,
        started_at.clone(),
        finished_at,
        changed_files.clone(),
    );
    result.command_line_preview = preview;
    result.stdout_truncated = stdout_truncated;
    result.stderr_truncated = stderr_truncated;
    result.capability_check_passed = cap_passed;
    if interim_status != ExternalCliExecutionStatus::Pending {
        result.status = interim_status;
    }

    emit(
        &app,
        FINISHED_EVENT,
        FinishedPayload {
            task_id: &req.task_id,
            workflow_run_id: &req.workflow_run_id,
            adapter_id: &cfg.adapter_id,
            runtime: runtime_str,
            status: result.status.as_str(),
            exit_code: result.exit_code,
            duration_ms: result.duration_ms,
            stdout_truncated,
            stderr_truncated,
            changed_files_count: changed_files.len(),
        },
    );

    result
}

fn error_result(
    req: &ExternalCliExecutionRequest,
    status: ExternalCliExecutionStatus,
    started_at: String,
    stdout: String,
    stderr: String,
    preview: String,
    cap_passed: bool,
) -> ExternalCliExecutionResult {
    let mut provider_meta = std::collections::HashMap::new();
    provider_meta.insert("adapter_type".into(), "external_cli".into());
    provider_meta.insert("runtime".into(), req.runtime.as_str().into());
    ExternalCliExecutionResult {
        task_id: req.task_id.clone(),
        workflow_run_id: req.workflow_run_id.clone(),
        adapter_id: req.adapter_id.clone(),
        adapter_name: req.adapter_id.clone(),
        runtime: req.runtime,
        status,
        cwd: req.cwd.clone(),
        command_line_preview: preview,
        exit_code: None,
        stdout,
        stderr,
        stdout_truncated: false,
        stderr_truncated: false,
        changed_files: vec![],
        duration_ms: 0,
        started_at: started_at.clone(),
        finished_at: now_iso(),
        capability_check_passed: cap_passed,
        provider_meta,
        metadata: req.metadata.clone(),
    }
}

#[allow(dead_code)]
pub fn unused_runtime_kind_marker(_k: ExternalCliRuntimeKind) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncate_short_passthrough() {
        let (s, t) = truncate_output("abc", 100);
        assert_eq!(s, "abc");
        assert!(!t);
    }

    #[test]
    fn truncate_long_chops() {
        let raw = "x".repeat(2000);
        let (s, t) = truncate_output(&raw, 1000);
        assert_eq!(s.len(), 1000);
        assert!(t);
    }

    #[test]
    fn validate_cwd_rejects_relative() {
        assert!(validate_cwd("rel/path").is_err());
    }

    #[test]
    fn validate_cwd_rejects_outside_home() {
        assert!(validate_cwd("/etc").is_err());
    }

    #[test]
    fn validate_cwd_accepts_home() {
        let home = std::env::var("HOME").unwrap();
        assert!(validate_cwd(&home).is_ok());
    }

    #[test]
    fn truncate_unicode_boundary_safe() {
        let s = "あ".repeat(10);
        let (out, t) = truncate_output(&s, 7);
        assert!(t);
        assert!(out.len() <= 7);
        assert!(out.chars().all(|c| c == 'あ'));
    }

    #[test]
    fn build_preview_truncates_long_lines() {
        let args: Vec<String> = (0..200).map(|i| format!("arg{i}")).collect();
        let p = build_command_line_preview("claude", &args);
        assert!(p.len() <= 405);
    }

    #[test]
    fn diff_detects_new_file() {
        let tmp = std::env::temp_dir().join(format!("nexmagi-rt-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let before = snapshot_top_level(&tmp);
        std::fs::write(tmp.join("new.txt"), "x").unwrap();
        let changed = diff_changed_files(&tmp, &before);
        assert_eq!(changed, vec!["new.txt".to_string()]);
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
