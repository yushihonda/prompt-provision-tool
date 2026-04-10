//! 共有型と `ExternalCliAdapter` トレイト。
//!
//! Claude Code 専用パスを汎化し、Codex / Generic CLI が
//! 同一インターフェースでプラグインできるようにする。
//!
//! - 共有 enum（`ExternalCliRuntimeKind`、`ExternalCliCapability`、
//!   `ExternalCliExecutionStatus`）
//! - 共有リクエスト/結果/設定型
//! - 具象アダプターが実装する `ExternalCliAdapter` トレイト
//! - 汎用ランナーは `external_cli_runner.rs` に実装され、
//!   このトレイトを実装するものを消費する
//!
//! `external_cli.rs` モジュールは公開 Tauri コマンドシグネチャを保持し、
//! 内部的にはリクエストを構築してレジストリ + このトレイト経由で
//! ディスパッチする。

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum ExternalCliRuntimeKind {
    ClaudeCode,
    Codex,
    Generic,
}

impl ExternalCliRuntimeKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExternalCliRuntimeKind::ClaudeCode => "claude_code",
            ExternalCliRuntimeKind::Codex => "codex",
            ExternalCliRuntimeKind::Generic => "generic",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum ExternalCliCapability {
    FileRead,
    FileWrite,
    ShellExec,
    DiffReview,
    LocalAuthSession,
    StructuredPatchSummary,
    BackgroundTask,
    StreamingStdout,
    StreamingStderr,
    WorkspaceAware,
    JsonOutput,
    Pty,
}

impl ExternalCliCapability {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExternalCliCapability::FileRead => "file_read",
            ExternalCliCapability::FileWrite => "file_write",
            ExternalCliCapability::ShellExec => "shell_exec",
            ExternalCliCapability::DiffReview => "diff_review",
            ExternalCliCapability::LocalAuthSession => "local_auth_session",
            ExternalCliCapability::StructuredPatchSummary => "structured_patch_summary",
            ExternalCliCapability::BackgroundTask => "background_task",
            ExternalCliCapability::StreamingStdout => "streaming_stdout",
            ExternalCliCapability::StreamingStderr => "streaming_stderr",
            ExternalCliCapability::WorkspaceAware => "workspace_aware",
            ExternalCliCapability::JsonOutput => "json_output",
            ExternalCliCapability::Pty => "pty",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExternalCliExecutionStatus {
    Pending,
    Running,
    Succeeded,
    Failed,
    TimedOut,
    Cancelled,
    MissingBinary,
    AuthRequired,
    CapabilityMismatch,
    Unsupported,
}

impl ExternalCliExecutionStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExternalCliExecutionStatus::Pending => "pending",
            ExternalCliExecutionStatus::Running => "running",
            ExternalCliExecutionStatus::Succeeded => "succeeded",
            ExternalCliExecutionStatus::Failed => "failed",
            ExternalCliExecutionStatus::TimedOut => "timed_out",
            ExternalCliExecutionStatus::Cancelled => "cancelled",
            ExternalCliExecutionStatus::MissingBinary => "missing_binary",
            ExternalCliExecutionStatus::AuthRequired => "auth_required",
            ExternalCliExecutionStatus::CapabilityMismatch => "capability_mismatch",
            ExternalCliExecutionStatus::Unsupported => "unsupported",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalCliAdapterConfig {
    pub adapter_id: String,
    pub adapter_name: String,
    pub runtime: ExternalCliRuntimeKind,
    pub command: String,
    #[serde(default)]
    pub default_args: Vec<String>,
    pub timeout_ms: Option<u64>,
    pub requires_local_auth: bool,
    pub capabilities: Vec<ExternalCliCapability>,
    #[serde(default)]
    pub env_keys_passthrough: Vec<String>,
    #[serde(default)]
    pub metadata: HashMap<String, String>,
    /// リスクレベル: low, medium, high, critical
    #[serde(default)]
    pub risk_level: Option<String>,
    /// このアダプターが隔離されたワークスペースを必要とするかどうか
    #[serde(default)]
    pub requires_workspace: bool,
    /// ステップが指定しない場合のデフォルト承認ポリシー
    #[serde(default)]
    pub default_approval_policy: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalCliExecutionRequest {
    pub task_id: String,
    pub workflow_run_id: String,
    pub task_role: Option<String>,
    pub adapter_id: String,
    pub runtime: ExternalCliRuntimeKind,
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    pub cwd: String,
    pub prompt: String,
    pub timeout_ms: u64,
    #[serde(default)]
    pub required_capabilities: Vec<ExternalCliCapability>,
    #[serde(default)]
    pub allow_writes: bool,
    #[serde(default)]
    pub allow_shell: bool,
    pub workspace_id: Option<String>,
    pub workspace_mode: Option<String>,
    #[serde(default)]
    pub workspace_path: Option<String>,
    #[serde(default)]
    pub approval_policy: Option<String>,
    #[serde(default)]
    pub selection_reason: Option<String>,
    /// CLI 専用モデル ID（例: "claude-sonnet-4-6"、"gpt-5-codex"）。
    /// 指定時はアダプターがランタイム固有のフラグ（Claude Code は `--model`、
    /// Codex は `-m`）を介して起動された CLI に転送する。
    /// None の場合は CLI のデフォルトプロファイルモデルを使用する。
    #[serde(default)]
    pub cli_model: Option<String>,
    #[serde(default)]
    pub env_overrides: HashMap<String, String>,
    #[serde(default)]
    pub metadata: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalCliExecutionResult {
    pub task_id: String,
    pub workflow_run_id: String,
    pub adapter_id: String,
    pub adapter_name: String,
    pub runtime: ExternalCliRuntimeKind,
    pub status: ExternalCliExecutionStatus,
    pub cwd: String,
    pub command_line_preview: String,
    pub exit_code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    pub changed_files: Vec<String>,
    /// 実行中に生成/変更されたファイルのファイル単位プレビュー。
    /// 各エントリは path、size、UTF-8 コンテンツの先頭 4KB、
    /// `truncated` フラグを持つ。変更がない場合は空。バックエンドはこれを
    /// アーティファクトの extra_metadata に転送し、UI が
    /// 「生成ファイル」パネルを表示できるようにする。
    #[serde(default)]
    pub changed_files_preview: Vec<crate::external_cli_runner::ChangedFilePreview>,
    pub duration_ms: u64,
    pub started_at: String,
    pub finished_at: String,
    pub capability_check_passed: bool,
    pub provider_meta: HashMap<String, String>,
    pub metadata: HashMap<String, String>,
}

/// すべての具象外部 CLI ランタイムが実装するトレイト。
///
/// 具象アダプターは*ランタイム固有*の振る舞いを担当する:
/// コマンド構築、プロンプトラッピング、失敗ヒューリスティクス、
/// 構造化出力パース、ケイパビリティ宣言。
///
/// 汎用ランナーは*ランタイム非依存*の振る舞いを担当する:
/// サブプロセス起動、タイムアウト、キャプチャ、切り詰め、
/// cwd バリデーション、変更ファイル検出、イベント送出。
pub trait ExternalCliAdapter: Send + Sync {
    fn adapter_config(&self) -> &ExternalCliAdapterConfig;

    /// このマシンでランタイムが現在実行可能か検証する。
    /// `Err(reason)` はコンテキストに応じてランナーが `MissingBinary`
    /// または `Unsupported` にマッピングする。
    fn validate_environment(&self) -> Result<(), String>;

    /// タスクが要求するケイパビリティとこのアダプターが宣言する
    /// ケイパビリティを比較する。要求されているがサポートされていない
    /// ケイパビリティのリストを `Err(missing)` として返す。
    fn supports_capabilities(
        &self,
        required: &[ExternalCliCapability],
    ) -> Result<(), Vec<ExternalCliCapability>> {
        let supported: std::collections::HashSet<_> = self
            .adapter_config()
            .capabilities
            .iter()
            .copied()
            .collect();
        let missing: Vec<_> = required
            .iter()
            .copied()
            .filter(|c| !supported.contains(c))
            .collect();
        if missing.is_empty() {
            Ok(())
        } else {
            Err(missing)
        }
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String>;

    fn build_prompt(&self, req: &ExternalCliExecutionRequest) -> Result<String, String> {
        Ok(req.prompt.clone())
    }

    fn classify_failure(
        &self,
        exit_code: Option<i32>,
        stdout: &str,
        stderr: &str,
        spawn_error_kind: Option<std::io::ErrorKind>,
    ) -> ExternalCliExecutionStatus;

    #[allow(clippy::too_many_arguments)]
    fn normalize_result(
        &self,
        req: &ExternalCliExecutionRequest,
        raw_stdout: String,
        raw_stderr: String,
        exit_code: Option<i32>,
        duration_ms: u64,
        started_at: String,
        finished_at: String,
        changed_files: Vec<String>,
    ) -> ExternalCliExecutionResult {
        let status = self.classify_failure(exit_code, &raw_stdout, &raw_stderr, None);
        let cfg = self.adapter_config();
        let mut provider_meta = HashMap::new();
        provider_meta.insert("adapter_type".into(), "external_cli".into());
        provider_meta.insert("runtime".into(), cfg.runtime.as_str().into());
        provider_meta.insert(
            "requires_local_auth".into(),
            cfg.requires_local_auth.to_string(),
        );
        ExternalCliExecutionResult {
            task_id: req.task_id.clone(),
            workflow_run_id: req.workflow_run_id.clone(),
            adapter_id: cfg.adapter_id.clone(),
            adapter_name: cfg.adapter_name.clone(),
            runtime: cfg.runtime,
            status,
            cwd: req.cwd.clone(),
            command_line_preview: String::new(),
            exit_code,
            stdout: raw_stdout,
            stderr: raw_stderr,
            stdout_truncated: false,
            stderr_truncated: false,
            changed_files,
            changed_files_preview: Vec::new(),
            duration_ms,
            started_at,
            finished_at,
            capability_check_passed: true,
            provider_meta,
            metadata: req.metadata.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct ToyAdapter {
        cfg: ExternalCliAdapterConfig,
    }
    impl ExternalCliAdapter for ToyAdapter {
        fn adapter_config(&self) -> &ExternalCliAdapterConfig {
            &self.cfg
        }
        fn validate_environment(&self) -> Result<(), String> {
            Ok(())
        }
        fn build_command(
            &self,
            _req: &ExternalCliExecutionRequest,
        ) -> Result<(String, Vec<String>), String> {
            Ok(("/bin/echo".into(), vec!["hi".into()]))
        }
        fn classify_failure(
            &self,
            exit_code: Option<i32>,
            _stdout: &str,
            _stderr: &str,
            _kind: Option<std::io::ErrorKind>,
        ) -> ExternalCliExecutionStatus {
            match exit_code {
                Some(0) => ExternalCliExecutionStatus::Succeeded,
                _ => ExternalCliExecutionStatus::Failed,
            }
        }
    }

    fn toy(caps: Vec<ExternalCliCapability>) -> ToyAdapter {
        ToyAdapter {
            cfg: ExternalCliAdapterConfig {
                adapter_id: "toy".into(),
                adapter_name: "Toy".into(),
                runtime: ExternalCliRuntimeKind::Generic,
                command: "/bin/echo".into(),
                default_args: vec![],
                timeout_ms: Some(1000),
                requires_local_auth: false,
                capabilities: caps,
                env_keys_passthrough: vec![],
                metadata: HashMap::new(),
            },
        }
    }

    #[test]
    fn supports_capabilities_passes_when_all_present() {
        let a = toy(vec![
            ExternalCliCapability::FileRead,
            ExternalCliCapability::FileWrite,
        ]);
        assert!(a
            .supports_capabilities(&[ExternalCliCapability::FileRead])
            .is_ok());
    }

    #[test]
    fn supports_capabilities_lists_missing() {
        let a = toy(vec![ExternalCliCapability::FileRead]);
        let err = a
            .supports_capabilities(&[
                ExternalCliCapability::FileRead,
                ExternalCliCapability::ShellExec,
            ])
            .unwrap_err();
        assert_eq!(err, vec![ExternalCliCapability::ShellExec]);
    }

    #[test]
    fn runtime_kind_as_str() {
        assert_eq!(ExternalCliRuntimeKind::ClaudeCode.as_str(), "claude_code");
        assert_eq!(ExternalCliRuntimeKind::Codex.as_str(), "codex");
        assert_eq!(ExternalCliRuntimeKind::Generic.as_str(), "generic");
    }

    #[test]
    fn capability_as_str_round_trip() {
        let caps = [
            ExternalCliCapability::FileRead,
            ExternalCliCapability::FileWrite,
            ExternalCliCapability::ShellExec,
            ExternalCliCapability::Pty,
        ];
        let strs: Vec<&str> = caps.iter().map(|c| c.as_str()).collect();
        assert_eq!(strs, vec!["file_read", "file_write", "shell_exec", "pty"]);
    }

    #[test]
    fn status_as_str() {
        assert_eq!(
            ExternalCliExecutionStatus::CapabilityMismatch.as_str(),
            "capability_mismatch"
        );
        assert_eq!(
            ExternalCliExecutionStatus::Unsupported.as_str(),
            "unsupported"
        );
    }
}
