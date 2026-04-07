"""External CLI adapter support — currently only Claude Code.

Builds the bundle payload that the Rust runtime layer uses to spawn the
external CLI. Distinct from internal cli_provider (local_worker) which
runs a packaged adapter binary owned by the app itself.

Claude Code is a *user-installed external* CLI tied to the user's
personal Pro/Max subscription. We never carry an Anthropic API key on
this path — auth is whatever the user has already done locally with
`claude login`.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.models import CoordinatorAdapter

ADAPTER_NAME_CLAUDE_CODE = "claude-code-local"
ADAPTER_NAME_CODEX = "codex-local"
ADAPTER_NAME_CURSOR = "cursor-local"
DEFAULT_CLAUDE_TIMEOUT_MS = 900_000  # 15 min


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
    approval_policy: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Convert a CoordinatorAdapter row into the runtime external_cli payload.

    Returns None for adapters that are not external_cli transport.
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
        "adapter_id": adapter.adapter_id,
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
        "approval_policy": approval_policy,
    }


def is_external_cli_payload(payload: Optional[dict[str, Any]]) -> bool:
    return bool(payload) and payload.get("transport") == "external_cli"
