"""外部 CLI アダプタ連携

Rust ランタイム層が外部 CLI を起動するための bundle payload を組み立てる。
内蔵の cli_provider (local_worker) とは異なり、ユーザーがローカルに
インストール済みの外部 CLI (Claude Code / Codex / Generic) を使う。

Claude Code はユーザー個人の Pro/Max サブスクに紐付く外部 CLI。
Anthropic API キーは一切載せず、`claude login` で済んだ認証をそのまま使う。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.models import CoordinatorAdapter

ADAPTER_NAME_CLAUDE_CODE = "claude-code-local"
ADAPTER_NAME_CODEX = "codex-local"
ADAPTER_NAME_CURSOR = "cursor-local"
DEFAULT_CLAUDE_TIMEOUT_MS = 900_000  # 15分


def build_external_cli_payload(
    adapter: Optional[CoordinatorAdapter],
    *,
    cwd: str,
    prompt: str,
    task_id: str,
    workflow_run_id: str,
    task_role: Optional[str] = None,
    allow_writes: bool = False,
    allow_shell: bool = False,
    timeout_ms: Optional[int] = None,
    required_capabilities: Optional[list[str]] = None,
    workspace_id: Optional[str] = None,
    workspace_mode: Optional[str] = None,
    workspace_path: Optional[str] = None,
    approval_policy: Optional[str] = None,
    selection_reason: Optional[str] = None,
    cli_model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """CoordinatorAdapter 行をランタイム用 external_cli payload に変換する。

    external_cli トランスポートでないアダプタの場合は None を返す。
    """
    if adapter is None or adapter.transport != "external_cli":
        return None

    config: dict[str, Any] = {}
    if adapter.config:
        try:
            config = json.loads(adapter.config)
        except json.JSONDecodeError:
            config = {}

    runtime = config.get("runtime", "claude_code")
    command = config.get("command", "claude")
    default_args = config.get("default_args") or []
    if not isinstance(default_args, list):
        default_args = []

    return {
        "transport": "external_cli",
        # adapter_id はデスクトップ Rust ExternalCliRegistry の検索キー。
        # 組み込みアダプタは "claude-code-local" / "codex-local" / "generic-cli" を
        # adapter_config().adapter_id として返す（DB の UUID ではない）。
        # よってここでは human-readable な adapter.name を送る。
        # DB UUID は監査/来歴用に adapter_db_id として別途保持。
        "adapter_id": adapter.name,
        "adapter_db_id": adapter.adapter_id,
        "adapter_name": adapter.name,
        "runtime": runtime,
        "command": command,
        "args": list(default_args),
        "cwd": cwd,
        "prompt": prompt,
        "task_id": task_id,
        "workflow_run_id": workflow_run_id,
        "task_role": task_role,
        "allow_writes": bool(allow_writes),
        "allow_shell": bool(allow_shell),
        "timeout_ms": int(timeout_ms or config.get("timeout_ms") or DEFAULT_CLAUDE_TIMEOUT_MS),
        "requires_local_auth": True,
        "required_capabilities": list(required_capabilities or []),
        "workspace_id": workspace_id,
        "workspace_mode": workspace_mode,
        "workspace_path": workspace_path,
        "approval_policy": approval_policy,
        "selection_reason": selection_reason,
        # CLI 専用モデル ID (例: "claude-sonnet-4-6")。
        # Rust runner が -m/--model として CLI コマンドに注入する。
        # None の場合は CLI のプロファイルデフォルトに従う。
        "cli_model": cli_model,
    }


def is_external_cli_payload(payload: Optional[dict[str, Any]]) -> bool:
    return bool(payload) and payload.get("transport") == "external_cli"
