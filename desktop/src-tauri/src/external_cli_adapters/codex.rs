//! OpenAI Codex CLI (`codex`) アダプター — スキャフォールド。
//!
//! Codex 呼び出しコントラクト（codex-cli 0.21.0 で検証済み）:
//!
//!   codex exec [--skip-git-repo-check] -s <sandbox> -C <cwd> "<prompt>"
//!
//! - `exec` は非インタラクティブサブコマンド（インタラクティブモードは
//!   プロンプト引数がなくランナーがハングする）。
//! - `-s read-only | workspace-write | danger-full-access` はステップの
//!   allow_writes / allow_shell フラグにマッピングされる。
//! - `-C <cwd>` はワークスペースルートとして扱うディレクトリを Codex に指示する。
//!   子プロセスも同じディレクトリに chdir する。
//! - `--skip-git-repo-check` は git リポジトリでないディレクトリ（テスト用
//!   ワークスペース、一時ディレクトリ）での Codex 実行を許可する。
//! - プロンプトは位置引数である。`-` を渡すと Codex は stdin から読み取るが、
//!   ここでは常にインラインで渡す。
//! - Codex の `-p` はプロファイルであり、プロンプトではない。Claude の -p を再利用しないこと。

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
                    // OPENAI_API_KEY は意図的に転送しない。
                    // ユーザーはローカル Codex CLI の ChatGPT Plus/Pro
                    // サブスクリプション認証（codex login）を使用するために
                    // 「CLI」を選択する。API キーが存在すると Codex はそれを
                    // 優先して API クレジットを消費する — まさにここで
                    // 避けたいことである。
                ],
                metadata: HashMap::new(),
                risk_level: Some("medium".into()),
                requires_workspace: true,
                default_approval_policy: Some("allow_write".into()),
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
        // TODO: `which codex` を検査する。現在は寛容にしており、`codex` が
        // ないマシンでもレジストリ構築が失敗しないようにしている。
        // 代わりにランナーが起動失敗時に MissingBinary を報告する。
        Ok(())
    }

    fn build_command(
        &self,
        req: &ExternalCliExecutionRequest,
    ) -> Result<(String, Vec<String>), String> {
        // ステップ承認ポリシー -> Codex サンドボックスポリシーのマッピング。
        // Claude Code スタイルのフラグはここには存在しない。`exec`
        // サブコマンドと -s (sandbox) および -C (cwd) を使用する。
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
        // オプショナルなモデルオーバーライド（例: "gpt-5-codex"）。Codex は
        // モデル選択に -m を使用する（-p ではない; -p はプロファイル）。
        // None の場合はフラグを完全にスキップし、Codex がデフォルトの
        // プロファイルモデルにフォールバックするようにする。
        if let Some(model) = req.cli_model.as_deref() {
            if !model.is_empty() {
                args.push("-m".into());
                args.push(model.to_string());
            }
        }
        // ユーザー提供の追加引数はその後に続く。
        args.extend(self.cfg.default_args.iter().cloned());
        args.extend(req.args.iter().cloned());
        // プロンプトは位置引数。
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
            cli_model: None,
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
        // -s read-only は読み取り専用承認用。
        let s_idx = args.iter().position(|a| a == "-s").unwrap();
        assert_eq!(args[s_idx + 1], "read-only");
        // -C で作業ディレクトリを指定。
        let c_idx = args.iter().position(|a| a == "-C").unwrap();
        assert_eq!(args[c_idx + 1], "/Users/me/project");
        // プロンプトは最後の位置引数。
        assert_eq!(args.last().unwrap(), "hello");
        // Codex は -p を使ってはいけない（プロファイルであり、プロンプトではない）。
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
        // Codex スキャフォールドはまだ PTY サポートを宣言していない — これは意図的である。
        assert!(!caps.contains(&ExternalCliCapability::Pty));
    }
}
