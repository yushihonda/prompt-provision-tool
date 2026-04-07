//! Claude Code (`claude`) adapter — concrete implementation of
//! `ExternalCliAdapter` for the local `claude` CLI.

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
        // TODO: real `which claude` check. Placeholder always succeeds
        // so the registry can be constructed even on machines without
        // `claude` installed; the runner will report MissingBinary on
        // spawn failure.
        Ok(())
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String> {
        let mut args: Vec<String> = self.cfg.default_args.clone();
        args.extend(req.args.iter().cloned());
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
