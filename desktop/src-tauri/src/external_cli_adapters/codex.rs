//! OpenAI Codex CLI (`codex`) adapter — scaffold.
//!
//! Codex invocation contract (verified against codex-cli 0.21.0):
//!
//!   codex exec [--skip-git-repo-check] -s <sandbox> -C <cwd> "<prompt>"
//!
//! - `exec` is the non-interactive subcommand (interactive mode has no
//!   prompt argument and would hang the runner).
//! - `-s read-only | workspace-write | danger-full-access` maps to the
//!   step's allow_writes / allow_shell flags.
//! - `-C <cwd>` tells Codex which directory to treat as the workspace
//!   root. We also chdir the child process to the same directory.
//! - `--skip-git-repo-check` allows Codex to run in directories that
//!   are not git repositories (test workspaces, temp dirs).
//! - The prompt is a positional argument. If `-` is passed, Codex
//!   reads from stdin; we always pass it inline.
//! - `-p` on Codex is profile, NOT prompt. Do not reuse Claude's -p.

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
        // TODO: probe `which codex`. Currently permissive so registry
        // construction does not fail on machines without `codex`; the
        // runner reports MissingBinary on spawn failure instead.
        Ok(())
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String> {
        // Map step approval policy -> codex sandbox policy.
        // Claude Code-style flags don't exist here; use the `exec`
        // subcommand with -s (sandbox) and -C (cwd).
        let sandbox = if req.allow_shell {
            "danger-full-access"
        } else if req.allow_writes {
            "workspace-write"
        } else {
            "read-only"
        };

        let mut args: Vec<String> = Vec::new();
        args.push("exec".into());
        args.push("--skip-git-repo-check".into());
        args.push("-s".into());
        args.push(sandbox.to_string());
        args.push("-C".into());
        args.push(req.cwd.clone());
        // Any extra user-provided args go next.
        args.extend(self.cfg.default_args.iter().cloned());
        args.extend(req.args.iter().cloned());
        // Prompt is a positional argument.
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

    fn dummy_req(allow_writes: bool, allow_shell: bool) -> ExternalCliExecutionRequest {
        ExternalCliExecutionRequest {
            task_id: "t".into(),
            workflow_run_id: "r".into(),
            task_role: None,
            adapter_id: "codex-local".into(),
            runtime: ExternalCliRuntimeKind::Codex,
            command: "codex".into(),
            args: vec![],
            cwd: "/Users/me/project".into(),
            prompt: "hello".into(),
            timeout_ms: 1000,
            required_capabilities: vec![],
            allow_writes,
            allow_shell,
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
    fn build_command_uses_exec_subcommand_and_positional_prompt() {
        let a = CodexAdapter::new();
        let (cmd, args) = a.build_command(&dummy_req(false, false)).unwrap();
        assert_eq!(cmd, "codex");
        assert_eq!(args[0], "exec");
        assert_eq!(args[1], "--skip-git-repo-check");
        // -s read-only for read-only approval.
        let s_idx = args.iter().position(|a| a == "-s").unwrap();
        assert_eq!(args[s_idx + 1], "read-only");
        // -C /cwd.
        let c_idx = args.iter().position(|a| a == "-C").unwrap();
        assert_eq!(args[c_idx + 1], "/Users/me/project");
        // Prompt is the last positional.
        assert_eq!(args.last().unwrap(), "hello");
        // Codex must NOT use -p (that's profile, not prompt).
        assert!(!args.contains(&"-p".to_string()));
    }

    #[test]
    fn build_command_sandbox_scales_with_approval() {
        let a = CodexAdapter::new();
        let (_, args_write) = a.build_command(&dummy_req(true, false)).unwrap();
        let s_idx = args_write.iter().position(|v| v == "-s").unwrap();
        assert_eq!(args_write[s_idx + 1], "workspace-write");

        let (_, args_shell) = a.build_command(&dummy_req(true, true)).unwrap();
        let s_idx = args_shell.iter().position(|v| v == "-s").unwrap();
        assert_eq!(args_shell[s_idx + 1], "danger-full-access");
    }

    #[test]
    fn capabilities_declared_correctly() {
        let a = CodexAdapter::new();
        let caps = &a.adapter_config().capabilities;
        assert!(caps.contains(&ExternalCliCapability::FileWrite));
        assert!(caps.contains(&ExternalCliCapability::ShellExec));
        // Codex scaffold does not declare PTY support yet — that's intentional.
        assert!(!caps.contains(&ExternalCliCapability::Pty));
    }
}
