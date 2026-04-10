//! `ExternalCliAdapter` インスタンス用の汎用ランナー。
//!
//! ランタイム非依存の処理を担当する:
//! - cwd バリデーション
//! - サブプロセス起動 (パイプモード — PTY モードは `external_cli_pty.rs` に実装)
//! - 行バッファリングされた stdout/stderr キャプチャとイベントストリーミング
//! - タイムアウト制御
//! - 変更ファイル差分検出
//! - 出力の切り詰め
//! - 統一的な `external_cli:*` イベントの送出
//!
//! 具象アダプターはコマンド構築、プロンプトラッピング、
//! 失敗分類、結果正規化を提供する。

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

use crate::external_cli_approval::{
    request_shell_approval, ApprovalDecision, ApprovalGate,
};
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
// ヘルパー関数
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
        // 文字境界でスライスする — 生のバイトオフセットではない — ので、
        // マルチバイトプロンプト（日本語、絵文字など）でパニックしない。
        // 過去の障害: 日本語プロンプトがバイト 400 のコードポイント途中に当たり、
        // consume_external_cli_bundle の async フューチャー内でパニックし、
        // JS 側の Tauri IPC Promise が永久にハングした。
        let cut = line
            .char_indices()
            .take_while(|(i, _)| *i <= 400)
            .last()
            .map(|(i, _)| i)
            .unwrap_or(0);
        format!("{}...", &line[..cut])
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

// ───────────────────────────────────────────────
// 「生成ファイル」プレビュー用の再帰的ワークスペーススナップショット
// ───────────────────────────────────────────────
//
// ワークスペースツリーを走査する（.git / node_modules / ドットディレクトリを除外）。
// 暴走した CLI が百万ノードを stat させないようにハード深度制限を設ける。
// (rel_path -> (size, mtime_ns)) をキャプチャする。
// diff_changed_files_recursive と組み合わせて新規 + 変更ファイルの両方を検出する。

const SNAPSHOT_MAX_DEPTH: usize = 6;
const SNAPSHOT_MAX_ENTRIES: usize = 5000;
const PREVIEW_MAX_FILES: usize = 30;
const PREVIEW_MAX_BYTES: usize = 4096;
const PREVIEW_SKIP_DIRS: &[&str] = &[".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build"];

#[derive(Debug, Clone, Serialize, serde::Deserialize)]
pub struct ChangedFilePreview {
    pub path: String,
    pub size: u64,
    /// ファイルの先頭 N バイトを UTF-8 として表示。非 UTF-8 ファイルは
    /// `is_binary: true` と空のプレビューを返す。
    pub preview: String,
    pub is_binary: bool,
    pub truncated: bool,
}

pub fn snapshot_recursive(cwd: &Path) -> std::collections::HashMap<PathBuf, (u64, i64)> {
    let mut out = std::collections::HashMap::new();
    walk_collect(cwd, cwd, 0, &mut out);
    out
}

fn walk_collect(
    root: &Path,
    dir: &Path,
    depth: usize,
    out: &mut std::collections::HashMap<PathBuf, (u64, i64)>,
) {
    if depth > SNAPSHOT_MAX_DEPTH || out.len() > SNAPSHOT_MAX_ENTRIES {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for e in entries.flatten() {
        let p = e.path();
        let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if PREVIEW_SKIP_DIRS.contains(&name) {
            continue;
        }
        let Ok(meta) = e.metadata() else { continue };
        if meta.is_dir() {
            walk_collect(root, &p, depth + 1, out);
        } else if meta.is_file() {
            // mtime を i64 ナノ秒として使用（ベストエフォート; 取得不可時は 0）。
            let mtime_ns = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_nanos() as i64)
                .unwrap_or(0);
            if let Ok(rel) = p.strip_prefix(root) {
                out.insert(rel.to_path_buf(), (meta.len(), mtime_ns));
            }
        }
        if out.len() > SNAPSHOT_MAX_ENTRIES {
            return;
        }
    }
}

/// 新規ファイル、または実行前のスナップショットから (size, mtime) が
/// 変化したファイルについて、ファイル単位のプレビューを構築する。
pub fn collect_changed_file_previews(
    cwd: &Path,
    before: &std::collections::HashMap<PathBuf, (u64, i64)>,
) -> Vec<ChangedFilePreview> {
    let after = snapshot_recursive(cwd);
    let mut changed: Vec<(PathBuf, u64)> = Vec::new();
    for (rel, (size_after, mtime_after)) in after.iter() {
        match before.get(rel) {
            Some((size_before, mtime_before))
                if size_before == size_after && mtime_before == mtime_after =>
            {
                // 変更なし
            }
            _ => changed.push((rel.clone(), *size_after)),
        }
    }
    changed.sort_by(|a, b| a.0.cmp(&b.0));
    changed.truncate(PREVIEW_MAX_FILES);

    let mut out: Vec<ChangedFilePreview> = Vec::with_capacity(changed.len());
    for (rel, size) in changed {
        let abs = cwd.join(&rel);
        let mut preview = String::new();
        let mut is_binary = false;
        let mut truncated = false;
        if let Ok(bytes) = std::fs::read(&abs) {
            let take = bytes.len().min(PREVIEW_MAX_BYTES);
            truncated = bytes.len() > PREVIEW_MAX_BYTES;
            match std::str::from_utf8(&bytes[..take]) {
                Ok(s) => preview = s.to_string(),
                Err(_) => {
                    is_binary = true;
                }
            }
        }
        out.push(ChangedFilePreview {
            path: rel.to_string_lossy().into_owned(),
            size,
            preview,
            is_binary,
            truncated,
        });
    }
    out
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
// イベントペイロード
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
// ストリーミング
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
// 汎用ランナー
// ───────────────────────────────────────────────

fn runner_trace(msg: &str) {
    use std::io::Write;
    let home = std::env::var("HOME").ok();
    let path = match home {
        Some(h) => std::path::PathBuf::from(h)
            .join("Library/Application Support/com.nexmagi.desktop/external_cli_runtime_trace.log"),
        None => std::path::PathBuf::from("/tmp/external_cli_runtime_trace.log"),
    };
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let ts = chrono::Utc::now().to_rfc3339();
        let _ = writeln!(f, "{} [runner] {}", ts, msg);
    }
}

pub async fn run_external_cli_with_adapter(
    registry: &ExternalCliRegistry,
    approval_gate: Option<&ApprovalGate>,
    app: AppHandle,
    req: ExternalCliExecutionRequest,
    cancel: Arc<AtomicBool>,
) -> ExternalCliExecutionResult {
    runner_trace(&format!("ENTER task_id={} adapter_id={} cwd={}", req.task_id, req.adapter_id, req.cwd));
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

    runner_trace(&format!("registry_lookup task_id={} adapter_id={}", req.task_id, req.adapter_id));
    // 1. レジストリ検索
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

    // 1.5 インタラクティブ承認ゲート (ask_before_shell)
    // ステップポリシーが ask_before_shell の場合、イベントを送出して
    // ユーザーが明示的にシェル実行を許可するのを待つ。承認されると
    // タスクの allow_shell フラグが昇格し、この単一実行に対して
    // ShellExec ケイパビリティが追加される。
    let mut req = req;
    if req.approval_policy.as_deref() == Some("ask_before_shell") {
        let gate = match approval_gate {
            Some(g) => g,
            None => {
                let reason = "ask_before_shell_requires_approval_gate_state".to_string();
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
                    false,
                );
            }
        };
        let decision = request_shell_approval(
            &app,
            gate,
            &req.task_id,
            &req.workflow_run_id,
            &cfg.adapter_id,
            runtime_str,
            &req.cwd,
            &req.prompt,
        )
        .await;
        match decision {
            ApprovalDecision::Approved => {
                req.allow_shell = true;
                if !req
                    .required_capabilities
                    .contains(&ExternalCliCapability::ShellExec)
                {
                    req.required_capabilities
                        .push(ExternalCliCapability::ShellExec);
                }
            }
            ApprovalDecision::Rejected | ApprovalDecision::TimedOut => {
                let reason_str = if decision == ApprovalDecision::TimedOut {
                    "approval_timed_out"
                } else {
                    "approval_rejected"
                };
                emit(
                    &app,
                    FAILED_EVENT,
                    FailedPayload {
                        task_id: &req.task_id,
                        workflow_run_id: &req.workflow_run_id,
                        adapter_id: &cfg.adapter_id,
                        runtime: runtime_str,
                        status: ExternalCliExecutionStatus::Cancelled.as_str(),
                        reason: reason_str,
                    },
                );
                return error_result(
                    &req,
                    ExternalCliExecutionStatus::Cancelled,
                    started_at,
                    String::new(),
                    reason_str.to_string(),
                    String::new(),
                    false,
                );
            }
        }
    }

    runner_trace(&format!("adapter_found task_id={}", req.task_id));
    // 2. 環境バリデーション
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

    // 3. ケイパビリティチェック
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

    runner_trace(&format!("pre_cwd_validate task_id={} cwd={}", req.task_id, req.cwd));
    // 4. 作業ディレクトリ
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

    runner_trace(&format!("cwd_validated task_id={} cwd={}", req.task_id, cwd.display()));
    // 5. コマンド + プロンプト
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
    // レンダリング済みプロンプトをリクエストに注入してからアダプターに
    // 引数構築を依頼する。一部のアダプターは req.prompt を直接参照するため。
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

    runner_trace(&format!("command_built task_id={} command={} args_len={}", req.task_id, command, args.len()));
    // 6. ファイルスナップショット（レガシー呼び出し元向けのトップレベル Vec<String>
    //    と、結果エンベロープで返されるリッチな「生成ファイル」プレビュー用の
    //    再帰的 (path -> size+mtime) マップ）。
    let started_files = snapshot_top_level(&cwd);
    let started_recursive = snapshot_recursive(&cwd);

    // 7. プロセス起動
    runner_trace(&format!("pre_spawn task_id={}", req.task_id));
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
        Ok(c) => {
            runner_trace(&format!("spawned task_id={} pid={:?}", req.task_id, c.id()));
            c
        },
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

    runner_trace(&format!("waiting task_id={} timeout_ms={}", req.task_id, req.timeout_ms));
    let timeout = Duration::from_millis(req.timeout_ms.max(1));
    let wait_result = tokio::time::timeout(timeout, child.wait()).await;
    runner_trace(&format!("wait_returned task_id={}", req.task_id));

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

    runner_trace(&format!("collecting_stdout task_id={}", req.task_id));
    let stdout_text = stdout_handle.await.unwrap_or_default();
    runner_trace(&format!("collecting_stderr task_id={}", req.task_id));
    let stderr_text = stderr_handle.await.unwrap_or_default();
    runner_trace(&format!("streams_collected task_id={} stdout_len={} stderr_len={}", req.task_id, stdout_text.len(), stderr_text.len()));
    let (stdout_trunc, stdout_truncated) = truncate_output(&stdout_text, MAX_OUTPUT_BYTES);
    let (stderr_trunc, stderr_truncated) = truncate_output(&stderr_text, MAX_OUTPUT_BYTES);
    let changed_files = diff_changed_files(&cwd, &started_files);
    // 再帰的 (path → size+mtime) 差分と先頭 4KB プレビュー。
    // バックエンド / UI がファイル名だけでなく*何が生成されたか*を表示できるようにする。
    let changed_files_preview = collect_changed_file_previews(&cwd, &started_recursive);
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
    result.changed_files_preview = changed_files_preview;
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
        changed_files_preview: vec![],
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
