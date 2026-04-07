//! Interactive approval gate for `ask_before_shell` steps.
//!
//! When a workflow step is resolved with `approval.policy ==
//! "ask_before_shell"` and the task needs shell execution, the runner
//! asks the user for confirmation before spawning. The flow is:
//!
//! 1. runner calls `ApprovalGate::request(app, summary)` which:
//!    - creates a fresh UUID `approval_id`
//!    - stores a `tokio::sync::oneshot` sender in the registry
//!    - emits `external_cli:approval_requested` with the id + summary
//!    - awaits the matching oneshot (bounded by timeout)
//! 2. the frontend modal subscribes to the event and asks the user
//! 3. frontend calls `external_cli_approve(approval_id)` or
//!    `external_cli_reject(approval_id)` Tauri commands, which resolve
//!    the oneshot with `Approved` or `Rejected`
//! 4. the runner receives the decision and either proceeds with shell
//!    capabilities enabled, or aborts with `CapabilityMismatch`
//!
//! Timeouts: if the user does not respond in 5 minutes, the request is
//! treated as rejected. This prevents a background run from blocking
//! forever.

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};
use tokio::sync::oneshot;

pub const APPROVAL_TIMEOUT_SECS: u64 = 300;
pub const APPROVAL_REQUESTED_EVENT: &str = "external_cli:approval_requested";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalDecision {
    Approved,
    Rejected,
    TimedOut,
}

#[derive(Serialize, Clone)]
pub struct ApprovalRequestPayload<'a> {
    pub approval_id: &'a str,
    pub task_id: &'a str,
    pub workflow_run_id: &'a str,
    pub adapter_id: &'a str,
    pub runtime: &'a str,
    pub cwd: &'a str,
    pub summary: &'a str,
    pub prompt_preview: &'a str,
}

#[derive(Default)]
pub struct ApprovalGate {
    inner: Mutex<HashMap<String, oneshot::Sender<ApprovalDecision>>>,
}

impl ApprovalGate {
    /// Register a pending approval and return the oneshot receiver.
    pub fn register(&self, approval_id: String) -> oneshot::Receiver<ApprovalDecision> {
        let (tx, rx) = oneshot::channel();
        self.inner.lock().insert(approval_id, tx);
        rx
    }

    /// Resolve a pending approval. Returns true if a sender was found.
    pub fn resolve(&self, approval_id: &str, decision: ApprovalDecision) -> bool {
        let Some(tx) = self.inner.lock().remove(approval_id) else {
            return false;
        };
        tx.send(decision).is_ok()
    }

    /// Drop a pending approval without notifying the receiver (used
    /// when the runner itself times out).
    pub fn drop_pending(&self, approval_id: &str) {
        self.inner.lock().remove(approval_id);
    }
}

/// Request approval from the user. Emits `external_cli:approval_requested`
/// and awaits a response or timeout.
pub async fn request_shell_approval(
    app: &AppHandle,
    gate: &ApprovalGate,
    task_id: &str,
    workflow_run_id: &str,
    adapter_id: &str,
    runtime: &str,
    cwd: &str,
    prompt: &str,
) -> ApprovalDecision {
    let approval_id = uuid::Uuid::new_v4().to_string();
    let rx = gate.register(approval_id.clone());

    let prompt_preview = if prompt.len() > 200 {
        &prompt[..200]
    } else {
        prompt
    };

    let _ = app.emit(
        APPROVAL_REQUESTED_EVENT,
        ApprovalRequestPayload {
            approval_id: &approval_id,
            task_id,
            workflow_run_id,
            adapter_id,
            runtime,
            cwd,
            summary: "ask_before_shell step requires shell execution",
            prompt_preview,
        },
    );

    match tokio::time::timeout(Duration::from_secs(APPROVAL_TIMEOUT_SECS), rx).await {
        Ok(Ok(decision)) => decision,
        Ok(Err(_canceled)) => {
            gate.drop_pending(&approval_id);
            ApprovalDecision::Rejected
        }
        Err(_timeout) => {
            gate.drop_pending(&approval_id);
            ApprovalDecision::TimedOut
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct ApprovalResolveRequest {
    pub approval_id: String,
}

#[tauri::command]
pub async fn external_cli_approve(
    gate: State<'_, ApprovalGate>,
    req: ApprovalResolveRequest,
) -> Result<bool, String> {
    Ok(gate.resolve(&req.approval_id, ApprovalDecision::Approved))
}

#[tauri::command]
pub async fn external_cli_reject(
    gate: State<'_, ApprovalGate>,
    req: ApprovalResolveRequest,
) -> Result<bool, String> {
    Ok(gate.resolve(&req.approval_id, ApprovalDecision::Rejected))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn approve_resolves_receiver() {
        let gate = ApprovalGate::default();
        let id = "test-id".to_string();
        let rx = gate.register(id.clone());
        assert!(gate.resolve(&id, ApprovalDecision::Approved));
        let decision = rx.await.unwrap();
        assert_eq!(decision, ApprovalDecision::Approved);
    }

    #[tokio::test]
    async fn reject_resolves_receiver() {
        let gate = ApprovalGate::default();
        let id = "test-id-2".to_string();
        let rx = gate.register(id.clone());
        assert!(gate.resolve(&id, ApprovalDecision::Rejected));
        let decision = rx.await.unwrap();
        assert_eq!(decision, ApprovalDecision::Rejected);
    }

    #[test]
    fn resolve_returns_false_for_unknown_id() {
        let gate = ApprovalGate::default();
        assert!(!gate.resolve("nonexistent", ApprovalDecision::Approved));
    }

    #[test]
    fn drop_pending_removes_sender() {
        let gate = ApprovalGate::default();
        let id = "pending".to_string();
        let _rx = gate.register(id.clone());
        gate.drop_pending(&id);
        assert!(!gate.resolve(&id, ApprovalDecision::Approved));
    }
}
