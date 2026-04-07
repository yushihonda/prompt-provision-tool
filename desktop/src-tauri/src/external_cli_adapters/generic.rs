//! Generic config-driven adapter.
//!
//! Used for two purposes:
//! 1. Tests can register a tiny shell script (e.g. `/bin/sh -c 'echo hi'`)
//!    as a "CLI" and exercise the full runner end-to-end without
//!    requiring real Claude/Codex authentication.
//! 2. End users can register their own coding CLIs without changes to
//!    the Rust code — once a frontend config path exists.

use std::collections::HashMap;
use std::io::ErrorKind;

use crate::external_cli_traits::{
    ExternalCliAdapter, ExternalCliAdapterConfig, ExternalCliExecutionRequest,
    ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

pub struct GenericAdapter {
    cfg: ExternalCliAdapterConfig,
}

impl GenericAdapter {
    pub fn new() -> Self {
        Self {
            cfg: ExternalCliAdapterConfig {
                adapter_id: "generic-cli".into(),
                adapter_name: "Generic CLI".into(),
                runtime: ExternalCliRuntimeKind::Generic,
                command: "/bin/sh".into(),
                default_args: vec!["-c".into()],
                timeout_ms: Some(60_000),
                requires_local_auth: false,
                capabilities: vec![],
                env_keys_passthrough: vec!["HOME".into(), "PATH".into(), "TERM".into()],
                metadata: HashMap::new(),
            },
        }
    }

    pub fn from_config(cfg: ExternalCliAdapterConfig) -> Self {
        Self { cfg }
    }
}

impl Default for GenericAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl ExternalCliAdapter for GenericAdapter {
    fn adapter_config(&self) -> &ExternalCliAdapterConfig {
        &self.cfg
    }

    fn validate_environment(&self) -> Result<(), String> {
        if self.cfg.command.is_empty() {
            return Err("generic_adapter_command_not_set".into());
        }
        Ok(())
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String> {
        // For Generic we treat `prompt` as the script body if `default_args`
        // looks like ["-c"] (sh-style), otherwise we pass it as a positional.
        let mut args: Vec<String> = self.cfg.default_args.clone();
        args.extend(req.args.iter().cloned());
        if !req.prompt.is_empty() {
            args.push(req.prompt.clone());
        }
        Ok((self.cfg.command.clone(), args))
    }

    fn classify_failure(
        &self,
        exit_code: Option<i32>,
        _stdout: &str,
        _stderr: &str,
        spawn_error_kind: Option<ErrorKind>,
    ) -> ExternalCliExecutionStatus {
        if matches!(spawn_error_kind, Some(ErrorKind::NotFound)) {
            return ExternalCliExecutionStatus::MissingBinary;
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
    fn classify_pure_exit_code() {
        let a = GenericAdapter::new();
        assert_eq!(
            a.classify_failure(Some(0), "", "", None),
            ExternalCliExecutionStatus::Succeeded
        );
        assert_eq!(
            a.classify_failure(Some(1), "", "", None),
            ExternalCliExecutionStatus::Failed
        );
        assert_eq!(
            a.classify_failure(None, "", "", Some(ErrorKind::NotFound)),
            ExternalCliExecutionStatus::MissingBinary
        );
    }

    #[test]
    fn build_command_appends_script_body() {
        let a = GenericAdapter::new();
        let req = ExternalCliExecutionRequest {
            task_id: "t".into(),
            workflow_run_id: "r".into(),
            task_role: None,
            adapter_id: "generic-cli".into(),
            runtime: ExternalCliRuntimeKind::Generic,
            command: "/bin/sh".into(),
            args: vec![],
            cwd: "/".into(),
            prompt: "echo hello".into(),
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
        };
        let (cmd, args) = a.build_command(&req).unwrap();
        assert_eq!(cmd, "/bin/sh");
        assert_eq!(args, vec!["-c".to_string(), "echo hello".to_string()]);
    }
}
