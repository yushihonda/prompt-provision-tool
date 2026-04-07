//! OpenAI Codex CLI (`codex`) adapter — scaffold.
//!
//! Phase 3.3 fills in the exact flag layout against `codex --help`. The
//! current scaffold uses a best-guess `-p <prompt>` invocation that
//! matches Claude's interface; if Codex requires a different layout,
//! only this file needs to change.

use std::collections::HashMap;
use std::io::ErrorKind;

use crate::external_cli_traits::{
    ExternalCliAdapter, ExternalCliAdapterConfig, ExternalCliCapability,
    ExternalCliExecutionRequest, ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

pub struct CodexAdapter {
    cfg: ExternalCliAdapterConfig,
}

impl CodexAdapter {
    pub fn new() -> Self {
        Self {
            cfg: ExternalCliAdapterConfig {
                adapter_id: "codex-local".into(),
                adapter_name: "OpenAI Codex Local CLI".into(),
                runtime: ExternalCliRuntimeKind::Codex,
                command: "codex".into(),
                default_args: vec![],
                timeout_ms: Some(900_000),
                requires_local_auth: true,
                capabilities: vec![
                    ExternalCliCapability::FileRead,
                    ExternalCliCapability::FileWrite,
                    ExternalCliCapability::ShellExec,
                    ExternalCliCapability::LocalAuthSession,
                    ExternalCliCapability::WorkspaceAware,
                    ExternalCliCapability::StreamingStdout,
                    ExternalCliCapability::StreamingStderr,
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
                    "OPENAI_API_KEY".into(),
                ],
                metadata: HashMap::new(),
            },
        }
    }
}

impl Default for CodexAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl ExternalCliAdapter for CodexAdapter {
    fn adapter_config(&self) -> &ExternalCliAdapterConfig {
        &self.cfg
    }

    fn validate_environment(&self) -> Result<(), String> {
        // Phase 3.3 will probe `which codex`. Phase 3.1 leaves it permissive
        // so registry construction does not fail on machines without codex.
        Ok(())
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String> {
        let mut args: Vec<String> = self.cfg.default_args.clone();
        args.extend(req.args.iter().cloned());
        // TODO(phase-3.3): verify against `codex --help`. If Codex uses
        // a subcommand like `codex exec` or accepts the prompt via stdin,
        // adjust here. Until then mirror Claude's `-p <prompt>` shape.
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
        if s.contains("not signed in")
            || s.contains("please run codex login")
            || s.contains("not authenticated")
            || s.contains("login required")
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

    #[test]
    fn classify_codex_auth_heuristic() {
        let a = CodexAdapter::new();
        let s = a.classify_failure(
            Some(1),
            "",
            "Error: not signed in. Please run codex login",
            None,
        );
        assert_eq!(s, ExternalCliExecutionStatus::AuthRequired);
    }

    #[test]
    fn capabilities_match_phase_plan() {
        let a = CodexAdapter::new();
        let caps = &a.adapter_config().capabilities;
        assert!(caps.contains(&ExternalCliCapability::FileWrite));
        assert!(caps.contains(&ExternalCliCapability::ShellExec));
        // Codex scaffold does not declare PTY support yet — that's intentional.
        assert!(!caps.contains(&ExternalCliCapability::Pty));
    }
}
