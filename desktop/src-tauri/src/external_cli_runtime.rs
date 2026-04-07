//! Desktop-side consumer for `execution_kind=external_cli` bundles.
//!
//! When the backend bundle response carries
//! `execution_kind="external_cli"` + `external_cli_payload`, the sidecar
//! returns a `delegated_to_external_cli_runtime` marker and stops. This
//! Tauri command picks the same execution up, runs it through the
//! registry-driven runner, and POSTs the completion back through the
//! existing `/api/worker/executions/{id}/complete` endpoint with an
//! `external_cli_meta` field.
//!
//! Currently this ships **on-demand fetch only** — the frontend
//! explicitly invokes `consume_external_cli_bundle(execution_id)`
//! after observing that the execution is sitting in the delegated
//! state. A background polling loop is a small follow-up; the
//! contract here is the same.

use std::collections::HashMap;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, State};

use crate::external_cli_approval::ApprovalGate;
use crate::external_cli_registry::ExternalCliRegistry;
use crate::external_cli_runner::run_external_cli_with_adapter;
use crate::external_cli_traits::{
    ExternalCliCapability, ExternalCliExecutionRequest, ExternalCliExecutionResult,
    ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

#[derive(Debug, Clone, Deserialize)]
pub struct ConsumeExternalCliRequest {
    pub api_base: String,
    pub auth_token: String,
    pub execution_id: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConsumeExternalCliResponse {
    pub execution_id: i64,
    pub status: String,
    pub adapter_id: String,
    pub runtime: String,
    pub exit_code: Option<i32>,
    pub duration_ms: u64,
    pub changed_files_count: usize,
    pub completion_posted: bool,
}

#[derive(Debug, Deserialize)]
struct BundleResponse {
    #[serde(default)]
    execution_kind: Option<String>,
    #[serde(default)]
    external_cli_payload: Option<serde_json::Value>,
    #[serde(default)]
    model: Option<String>,
}

fn cap_from_str(s: &str) -> Option<ExternalCliCapability> {
    Some(match s {
        "file_read" => ExternalCliCapability::FileRead,
        "file_write" => ExternalCliCapability::FileWrite,
        "shell_exec" => ExternalCliCapability::ShellExec,
        "diff_review" => ExternalCliCapability::DiffReview,
        "local_auth_session" => ExternalCliCapability::LocalAuthSession,
        "structured_patch_summary" => ExternalCliCapability::StructuredPatchSummary,
        "background_task" => ExternalCliCapability::BackgroundTask,
        "streaming_stdout" => ExternalCliCapability::StreamingStdout,
        "streaming_stderr" => ExternalCliCapability::StreamingStderr,
        "workspace_aware" => ExternalCliCapability::WorkspaceAware,
        "json_output" => ExternalCliCapability::JsonOutput,
        "pty" => ExternalCliCapability::Pty,
        _ => return None,
    })
}

fn runtime_from_str(s: &str) -> ExternalCliRuntimeKind {
    match s {
        "claude_code" => ExternalCliRuntimeKind::ClaudeCode,
        "codex" => ExternalCliRuntimeKind::Codex,
        _ => ExternalCliRuntimeKind::Generic,
    }
}

fn payload_to_request(
    payload: serde_json::Value,
) -> Result<ExternalCliExecutionRequest, String> {
    let obj = payload
        .as_object()
        .ok_or_else(|| "external_cli_payload_not_object".to_string())?;
    let runtime_str = obj
        .get("runtime")
        .and_then(|v| v.as_str())
        .unwrap_or("generic");
    let required_capabilities: Vec<ExternalCliCapability> = obj
        .get("required_capabilities")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().and_then(cap_from_str))
                .collect()
        })
        .unwrap_or_default();
    let args: Vec<String> = obj
        .get("args")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    let env_overrides: HashMap<String, String> = obj
        .get("env_overrides")
        .and_then(|v| v.as_object())
        .map(|m| {
            m.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                .collect()
        })
        .unwrap_or_default();

    Ok(ExternalCliExecutionRequest {
        task_id: obj
            .get("task_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        workflow_run_id: obj
            .get("workflow_run_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        task_role: obj
            .get("task_role")
            .and_then(|v| v.as_str())
            .map(String::from),
        adapter_id: obj
            .get("adapter_id")
            .and_then(|v| v.as_str())
            .ok_or("missing adapter_id")?
            .to_string(),
        runtime: runtime_from_str(runtime_str),
        command: obj
            .get("command")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        args,
        cwd: obj
            .get("cwd")
            .and_then(|v| v.as_str())
            .ok_or("missing cwd")?
            .to_string(),
        prompt: obj
            .get("prompt")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        timeout_ms: obj
            .get("timeout_ms")
            .and_then(|v| v.as_u64())
            .unwrap_or(900_000),
        required_capabilities,
        allow_writes: obj
            .get("allow_writes")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        allow_shell: obj
            .get("allow_shell")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        workspace_id: obj
            .get("workspace_id")
            .and_then(|v| v.as_str())
            .map(String::from),
        workspace_mode: obj
            .get("workspace_mode")
            .and_then(|v| v.as_str())
            .map(String::from),
        workspace_path: obj
            .get("workspace_path")
            .and_then(|v| v.as_str())
            .map(String::from),
        approval_policy: obj
            .get("approval_policy")
            .and_then(|v| v.as_str())
            .map(String::from),
        selection_reason: obj
            .get("selection_reason")
            .and_then(|v| v.as_str())
            .map(String::from),
        env_overrides,
        metadata: HashMap::new(),
    })
}

fn build_external_cli_meta(
    result: &ExternalCliExecutionResult,
    req: &ExternalCliExecutionRequest,
) -> serde_json::Value {
    let required_caps: Vec<&str> = req
        .required_capabilities
        .iter()
        .map(|c| c.as_str())
        .collect();
    serde_json::json!({
        "adapter_id": result.adapter_id,
        "adapter_name": result.adapter_name,
        "runtime": result.runtime.as_str(),
        "status": result.status.as_str(),
        "cwd": result.cwd,
        "command": req.command,
        "command_line_preview": result.command_line_preview,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "changed_files": result.changed_files,
        "capability_check_passed": result.capability_check_passed,
        "task_id": result.task_id,
        "workflow_run_id": result.workflow_run_id,
        // Provenance echoed back from the request so completion_service
        // can build a full audit row from a single dict.
        "selection_reason": req.selection_reason,
        "approval_policy": req.approval_policy,
        "required_capabilities": required_caps,
        "allow_writes": req.allow_writes,
        "allow_shell": req.allow_shell,
        "workspace_id": req.workspace_id,
        "workspace_mode": req.workspace_mode,
        "workspace_path": req.workspace_path,
    })
}

fn fetch_bundle(api_base: &str, auth_token: &str, execution_id: i64) -> Result<BundleResponse, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| format!("client_build: {e}"))?;
    let url = format!(
        "{}/api/worker/executions/{}/bundle",
        api_base.trim_end_matches('/'),
        execution_id
    );
    let resp = client
        .get(&url)
        .bearer_auth(auth_token)
        .send()
        .map_err(|e| format!("fetch_bundle_failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("fetch_bundle_http_{}", resp.status().as_u16()));
    }
    resp.json::<BundleResponse>()
        .map_err(|e| format!("bundle_parse: {e}"))
}

fn post_completion(
    api_base: &str,
    auth_token: &str,
    execution_id: i64,
    result: &ExternalCliExecutionResult,
    req: &ExternalCliExecutionRequest,
) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| format!("client_build: {e}"))?;
    let url = format!(
        "{}/api/worker/executions/{}/complete",
        api_base.trim_end_matches('/'),
        execution_id
    );
    let body = serde_json::json!({
        "output": format!(
            "[external_cli {}]\nstatus: {}\nexit_code: {:?}\nchanged_files: {:?}\n\n--- stdout ---\n{}\n--- stderr ---\n{}",
            result.runtime.as_str(),
            result.status.as_str(),
            result.exit_code,
            result.changed_files,
            result.stdout,
            result.stderr,
        ),
        "tokens_used": 0,
        "model_used": result.runtime.as_str(),
        "execution_time_ms": result.duration_ms,
        "external_cli_meta": build_external_cli_meta(result, req),
    });
    let resp = client
        .post(&url)
        .bearer_auth(auth_token)
        .json(&body)
        .send()
        .map_err(|e| format!("post_completion_failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("post_completion_http_{}", resp.status().as_u16()));
    }
    Ok(())
}

#[tauri::command]
pub async fn consume_external_cli_bundle(
    app: AppHandle,
    registry: State<'_, ExternalCliRegistry>,
    approval_gate: State<'_, ApprovalGate>,
    req: ConsumeExternalCliRequest,
) -> Result<ConsumeExternalCliResponse, String> {
    // Step 1: fetch bundle (sync via spawn_blocking to keep this async-friendly).
    let api_base = req.api_base.clone();
    let auth_token = req.auth_token.clone();
    let execution_id = req.execution_id;
    let bundle = tokio::task::spawn_blocking(move || {
        fetch_bundle(&api_base, &auth_token, execution_id)
    })
    .await
    .map_err(|e| format!("join_fetch: {e}"))??;

    if bundle.execution_kind.as_deref() != Some("external_cli") {
        return Err(format!(
            "execution_kind_not_external_cli: got {:?}",
            bundle.execution_kind
        ));
    }
    let payload = bundle
        .external_cli_payload
        .ok_or_else(|| "external_cli_payload_missing".to_string())?;
    let mut cli_req = payload_to_request(payload)?;

    // If the bundle reserved a workspace but the path is not yet on
    // disk, materialize it via crate::workspaces and POST the path
    // back to the backend. After this the cwd we hand to the adapter
    // is guaranteed to exist.
    if let Some(ws_id) = cli_req.workspace_id.clone() {
        if cli_req.workspace_path.is_none() || cli_req.cwd.is_empty() {
            let ensure_req = crate::workspaces::WorkspaceEnsureRequest {
                api_base: req.api_base.clone(),
                auth_token: req.auth_token.clone(),
                workspace_id: ws_id.clone(),
                plan_id: cli_req.workflow_run_id.clone(),
                task_id: cli_req.task_id.clone(),
            };
            let ensured = crate::workspaces::workspace_ensure_dir(ensure_req).await?;
            cli_req.cwd = ensured.workspace_path.clone();
            cli_req.workspace_path = Some(ensured.workspace_path);
        }
    }

    // Keep a clone for the completion POST so we can echo provenance
    // (selection_reason, approval_policy, capabilities) back to the
    // backend. The runner consumes the original request.
    let cli_req_for_post = cli_req.clone();

    // Step 2: run via registry-driven runner.
    let cancel = Arc::new(AtomicBool::new(false));
    let result = run_external_cli_with_adapter(
        &registry,
        Some(&approval_gate),
        app,
        cli_req,
        cancel,
    )
    .await;

    // Step 3: post completion (best effort).
    let api_base = req.api_base.clone();
    let auth_token = req.auth_token.clone();
    let result_for_post = result.clone();
    let post_outcome = tokio::task::spawn_blocking(move || {
        post_completion(
            &api_base,
            &auth_token,
            execution_id,
            &result_for_post,
            &cli_req_for_post,
        )
    })
    .await
    .map_err(|e| format!("join_post: {e}"))?;
    let completion_posted = post_outcome.is_ok();
    if let Err(e) = post_outcome {
        eprintln!("[external_cli_runtime] post_completion error: {e}");
    }

    Ok(ConsumeExternalCliResponse {
        execution_id,
        status: result.status.as_str().into(),
        adapter_id: result.adapter_id.clone(),
        runtime: result.runtime.as_str().into(),
        exit_code: result.exit_code,
        duration_ms: result.duration_ms,
        changed_files_count: result.changed_files.len(),
        completion_posted,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cap_from_str_known() {
        assert_eq!(
            cap_from_str("file_write"),
            Some(ExternalCliCapability::FileWrite)
        );
        assert_eq!(cap_from_str("pty"), Some(ExternalCliCapability::Pty));
        assert_eq!(cap_from_str("nonsense"), None);
    }

    #[test]
    fn runtime_from_str_known() {
        assert_eq!(
            runtime_from_str("claude_code"),
            ExternalCliRuntimeKind::ClaudeCode
        );
        assert_eq!(runtime_from_str("codex"), ExternalCliRuntimeKind::Codex);
        assert_eq!(
            runtime_from_str("anything-else"),
            ExternalCliRuntimeKind::Generic
        );
    }

    #[test]
    fn payload_to_request_minimum() {
        let v = serde_json::json!({
            "adapter_id": "claude-code-local",
            "runtime": "claude_code",
            "cwd": "/tmp",
            "prompt": "hi",
            "timeout_ms": 5000,
        });
        let r = payload_to_request(v).unwrap();
        assert_eq!(r.adapter_id, "claude-code-local");
        assert_eq!(r.cwd, "/tmp");
        assert_eq!(r.runtime, ExternalCliRuntimeKind::ClaudeCode);
    }

    #[test]
    fn payload_missing_adapter_id_errors() {
        let v = serde_json::json!({"cwd": "/tmp"});
        assert!(payload_to_request(v).is_err());
    }
}
