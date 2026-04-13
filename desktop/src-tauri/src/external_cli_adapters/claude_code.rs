//! Claude Code (`claude`) アダプター — ローカル `claude` CLI 用の
//! `ExternalCliAdapter` 具象実装。

use std::collections::HashMap;
use std::io::ErrorKind;

use crate::external_cli_traits::{
    ExternalCliAdapter, ExternalCliAdapterConfig, ExternalCliCapability,
    ExternalCliExecutionRequest, ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

pub struct ClaudeCodeAdapter {
    cfg: ExternalCliAdapterConfig,
}

impl ClaudeCodeAdapter {
    pub fn new() -> Self {
        Self {
            cfg: ExternalCliAdapterConfig {
                adapter_id: "claude-code-local".into(),
                adapter_name: "Claude Code Local CLI".into(),
                runtime: ExternalCliRuntimeKind::ClaudeCode,
                command: "claude".into(),
                default_args: vec![],
                timeout_ms: Some(900_000),
                requires_local_auth: true,
                capabilities: vec![
                    ExternalCliCapability::FileRead,
                    ExternalCliCapability::FileWrite,
                    ExternalCliCapability::ShellExec,
                    ExternalCliCapability::DiffReview,
                    ExternalCliCapability::LocalAuthSession,
                    ExternalCliCapability::WorkspaceAware,
                    ExternalCliCapability::StreamingStdout,
                    ExternalCliCapability::StreamingStderr,
                    ExternalCliCapability::Pty,
                ],
                env_keys_passthrough: vec![
                    "HOME".into(),
                    "PATH".into(),
                    "USER".into(),
                    "LOGNAME".into(),
                    "SHELL".into(),
                    "LANG".into(),
                    "LC_ALL".into(),
                    "TERM".into(),
                    "TMPDIR".into(),
                    "ANTHROPIC_CONFIG_DIR".into(),
                ],
                metadata: HashMap::new(),
                risk_level: Some("medium".into()),
                requires_workspace: true,
                default_approval_policy: Some("ask_before_shell".into()),
            },
        }
    }
}

impl Default for ClaudeCodeAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl ExternalCliAdapter for ClaudeCodeAdapter {
    fn adapter_config(&self) -> &ExternalCliAdapterConfig {
        &self.cfg
    }

    fn validate_environment(&self) -> Result<(), String> {
        // TODO: 実際の `which claude` チェック。プレースホルダーとして常に成功する。
        // `claude` がインストールされていないマシンでもレジストリを構築できるようにするため。
        // ランナーが起動失敗時に MissingBinary を報告する。
        Ok(())
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String> {
        let mut args: Vec<String> = self.cfg.default_args.clone();
        args.extend(req.args.iter().cloned());
        // オプショナルなモデルオーバーライド（例: "claude-sonnet-4-6"）。
        // Claude Code は --model NAME を受け付ける。None = デフォルトプロファイルモデル。
        if let Some(model) = req.cli_model.as_deref() {
            if !model.is_empty() {
                args.push("--model".into());
                args.push(model.to_string());
            }
        }
        // パーミッションモードマッピング（Codex サンドボックスフラグレイヤーに対応）。
        // このフラグがないと claude は Edit/Write ツールを拒否し、
        // ワークフローの「実装」ステップは書き込む内容のテキスト説明のみを返し、
        // cwd が空のままになる。allow_shell は最強モードを意味し、
        // allow_writes のみでもファイル編集には十分である。
        if req.allow_shell {
            args.push("--permission-mode".into());
            args.push("bypassPermissions".into());
        } else if req.allow_writes {
            args.push("--permission-mode".into());
            args.push("acceptEdits".into());
        }
        args.push("-p".into());
        args.push(req.prompt.clone());
        Ok((self.cfg.command.clone(), args))
    }

    fn classify_failure(
        &self,
        exit_code: Option<i32>,
        _stdout: &str,
        stderr: &str,
        spawn_error_kind: Option<ErrorKind>,
    ) -> ExternalCliExecutionStatus {
        if matches!(spawn_error_kind, Some(ErrorKind::NotFound)) {
            return ExternalCliExecutionStatus::MissingBinary;
        }
        let s = stderr.to_lowercase();
        if s.contains("not authenticated")
            || s.contains("login required")
            || s.contains("please run claude login")
            || s.contains("please run `claude login`")
        {
            return ExternalCliExecutionStatus::AuthRequired;
        }
        match exit_code {
            Some(0) => ExternalCliExecutionStatus::Succeeded,
            _ => ExternalCliExecutionStatus::Failed,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_req() -> ExternalCliExecutionRequest {
        ExternalCliExecutionRequest {
            task_id: "t".into(),
            workflow_run_id: "r".into(),
            task_role: None,
            adapter_id: "claude-code-local".into(),
            runtime: ExternalCliRuntimeKind::ClaudeCode,
            command: "claude".into(),
            args: vec![],
            cwd: "/".into(),
            prompt: "say hi".into(),
            timeout_ms: 1000,
            required_capabilities: vec![],
            allow_writes: false,
            allow_shell: false,
            workspace_id: None,
            workspace_mode: None,
            workspace_path: None,
            approval_policy: None,
            selection_reason: None,
            cli_model: None,
            env_overrides: HashMap::new(),
            metadata: HashMap::new(),
        }
    }

    #[test]
    fn build_command_appends_prompt_with_dash_p() {
        let a = ClaudeCodeAdapter::new();
        let (cmd, args) = a.build_command(&dummy_req()).unwrap();
        assert_eq!(cmd, "claude");
        assert_eq!(args, vec!["-p".to_string(), "say hi".to_string()]);
    }

    #[test]
    fn classify_auth_required_heuristic() {
        let a = ClaudeCodeAdapter::new();
        let s = a.classify_failure(
            Some(1),
            "",
            "Error: not authenticated\nplease run claude login",
            None,
        );
        assert_eq!(s, ExternalCliExecutionStatus::AuthRequired);
    }

    #[test]
    fn classify_missing_binary_via_spawn_kind() {
        let a = ClaudeCodeAdapter::new();
        let s = a.classify_failure(None, "", "", Some(ErrorKind::NotFound));
        assert_eq!(s, ExternalCliExecutionStatus::MissingBinary);
    }

    #[test]
    fn capabilities_include_pty_and_workspace() {
        let a = ClaudeCodeAdapter::new();
        let caps = &a.adapter_config().capabilities;
        assert!(caps.contains(&ExternalCliCapability::Pty));
        assert!(caps.contains(&ExternalCliCapability::WorkspaceAware));
    }
}
