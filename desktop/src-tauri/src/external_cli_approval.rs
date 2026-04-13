//! `ask_before_shell` ステップ用のインタラクティブ承認ゲート。
//!
//! ワークフローステップが `approval.policy == "ask_before_shell"` で解決され、
//! タスクがシェル実行を必要とする場合、ランナーは起動前にユーザーに確認を求める。
//! フローは以下の通り:
//!
//! 1. ランナーが `ApprovalGate::request(app, summary)` を呼び出す:
//!    - 新しい UUID `approval_id` を生成
//!    - `tokio::sync::oneshot` の送信側をレジストリに格納
//!    - id + summary 付きで `external_cli:approval_requested` を送出
//!    - 対応する oneshot を待機（タイムアウト付き）
//! 2. フロントエンドのモーダルがイベントを購読してユーザーに問い合わせる
//! 3. フロントエンドが `external_cli_approve(approval_id)` または
//!    `external_cli_reject(approval_id)` Tauri コマンドを呼び出し、
//!    oneshot を `Approved` または `Rejected` で解決する
//! 4. ランナーが決定を受け取り、シェルケイパビリティを有効にして続行するか、
//!    `CapabilityMismatch` で中止する
//!
//! タイムアウト: ユーザーが 5 分以内に応答しない場合、リクエストは
//! 拒否として扱われる。これによりバックグラウンド実行が
//! 永久にブロックされることを防ぐ。

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
    /// 保留中の承認を登録し、oneshot レシーバーを返す。
    pub fn register(&self, approval_id: String) -> oneshot::Receiver<ApprovalDecision> {
        let (tx, rx) = oneshot::channel();
        self.inner.lock().insert(approval_id, tx);
        rx
    }

    /// 保留中の承認を解決する。送信側が見つかった場合は true を返す。
    pub fn resolve(&self, approval_id: &str, decision: ApprovalDecision) -> bool {
        let Some(tx) = self.inner.lock().remove(approval_id) else {
            return false;
        };
        tx.send(decision).is_ok()
    }

    /// レシーバーに通知せずに保留中の承認を破棄する
    /// （ランナー自体がタイムアウトした場合に使用）。
    pub fn drop_pending(&self, approval_id: &str) {
        self.inner.lock().remove(approval_id);
    }
}

/// ユーザーに承認を要求する。`external_cli:approval_requested` を送出し、
/// 応答またはタイムアウトを待機する。
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

    // 文字境界でスライスする — 生のバイトインデックスは
    // マルチバイトプロンプト（日本語/絵文字）でパニックする。
    // フィードバックメモリ「Rust string slicing must respect char boundaries」を参照。
    let prompt_preview_owned: String;
    let prompt_preview: &str = if prompt.len() > 200 {
        let mut cut = 200;
        while cut > 0 && !prompt.is_char_boundary(cut) {
            cut -= 1;
        }
        prompt_preview_owned = prompt[..cut].to_string();
        &prompt_preview_owned
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

/// ローカル oneshot を解決し、かつバックエンドに決定を同期する
/// 統合承認レスポンス。フロントエンドはワークフローステップに対して
/// `external_cli_approve` / `external_cli_reject` の代わりにこれを呼び出すべきである。
#[derive(Debug, Deserialize)]
pub struct WorkflowApprovalResponse {
    pub approval_id: String,
    /// "granted" | "rejected" のいずれか
    pub decision: String,
    pub api_base: String,
    pub auth_token: String,
    pub workflow_execution_id: i64,
    /// 作成と解決のためのオプショナルな出自フィールド
    pub step_id: Option<String>,
    pub adapter_id: Option<String>,
    pub runtime: Option<String>,
    pub cwd: Option<String>,
    pub prompt_preview: Option<String>,
}

#[tauri::command]
pub async fn submit_workflow_approval_response(
    gate: State<'_, ApprovalGate>,
    req: WorkflowApprovalResponse,
) -> Result<bool, String> {
    // 1. ローカル oneshot を解決
    let local_decision = match req.decision.as_str() {
        "granted" => ApprovalDecision::Approved,
        "rejected" => ApprovalDecision::Rejected,
        _ => ApprovalDecision::Rejected,
    };
    let _ = gate.resolve(&req.approval_id, local_decision);

    // 2. バックエンドに同期（ベストエフォート、ファイア・アンド・フォーゲット）
    let api_base = req.api_base.clone();
    let auth_token = req.auth_token.clone();
    let approval_id = req.approval_id.clone();
    let decision = req.decision.clone();
    let wf_exec_id = req.workflow_execution_id;
    let step_id = req.step_id.clone();
    let adapter_id = req.adapter_id.clone();
    let runtime = req.runtime.clone();
    let cwd = req.cwd.clone();
    let prompt_preview = req.prompt_preview.clone();

    tokio::task::spawn_blocking(move || {
        let url = format!(
            "{}/api/user/workflow-executions/{}/approvals/{}/respond",
            api_base.trim_end_matches('/'),
            wf_exec_id,
            approval_id,
        );
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .ok();
        if let Some(client) = client {
            let mut form = vec![
                ("decision".to_string(), decision),
            ];
            if let Some(sid) = step_id {
                form.push(("step_id".to_string(), sid));
            }
            if let Some(aid) = adapter_id {
                form.push(("adapter_id".to_string(), aid));
            }
            if let Some(rt) = runtime {
                form.push(("runtime".to_string(), rt));
            }
            if let Some(c) = cwd {
                form.push(("cwd".to_string(), c));
            }
            if let Some(pp) = prompt_preview {
                form.push(("prompt_preview".to_string(), pp));
            }
            let _ = client
                .post(&url)
                .header("Authorization", format!("Bearer {}", auth_token))
                .form(&form)
                .send();
        }
    });

    Ok(true)
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
