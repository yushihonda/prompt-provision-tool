"""Capability constants + role/policy → required-capability mapping.

Mirrors `desktop/src-tauri/src/external_cli_traits.rs::ExternalCliCapability`.
The two sides MUST agree on the snake_case strings — they cross the
bundle/JSON boundary in `external_cli_payload.required_capabilities`.
"""
from __future__ import annotations

from typing import Iterable

# ── capability constants ─────────────────────────────────────────────
CAP_FILE_READ = "file_read"
CAP_FILE_WRITE = "file_write"
CAP_SHELL_EXEC = "shell_exec"
CAP_DIFF_REVIEW = "diff_review"
CAP_LOCAL_AUTH_SESSION = "local_auth_session"
CAP_STRUCTURED_PATCH_SUMMARY = "structured_patch_summary"
CAP_BACKGROUND_TASK = "background_task"
CAP_STREAMING_STDOUT = "streaming_stdout"
CAP_STREAMING_STDERR = "streaming_stderr"
CAP_WORKSPACE_AWARE = "workspace_aware"
CAP_JSON_OUTPUT = "json_output"
CAP_PTY = "pty"

ALL_CAPABILITIES: tuple[str, ...] = (
    CAP_FILE_READ,
    CAP_FILE_WRITE,
    CAP_SHELL_EXEC,
    CAP_DIFF_REVIEW,
    CAP_LOCAL_AUTH_SESSION,
    CAP_STRUCTURED_PATCH_SUMMARY,
    CAP_BACKGROUND_TASK,
    CAP_STREAMING_STDOUT,
    CAP_STREAMING_STDERR,
    CAP_WORKSPACE_AWARE,
    CAP_JSON_OUTPUT,
    CAP_PTY,
)


def required_capabilities_for_task(
    *,
    role: str | None,
    writes_files: bool,
    allow_shell: bool,
    has_workspace: bool,
    requires_local_auth: bool = True,
) -> list[str]:
    """Compute the required-capability list for a task.

    The runner compares this against the adapter's declared capabilities
    before spawning. A mismatch returns CapabilityMismatch with no spawn.
    """
    caps: list[str] = [CAP_FILE_READ]
    if writes_files:
        caps.append(CAP_FILE_WRITE)
    if allow_shell:
        caps.append(CAP_SHELL_EXEC)
    if has_workspace:
        caps.append(CAP_WORKSPACE_AWARE)
    if requires_local_auth:
        caps.append(CAP_LOCAL_AUTH_SESSION)
    # Streaming is always required for the visible terminal viewer.
    caps.append(CAP_STREAMING_STDOUT)
    caps.append(CAP_STREAMING_STDERR)
    return caps


def is_known_capability(cap: str) -> bool:
    return cap in ALL_CAPABILITIES


def normalize_capabilities(caps: Iterable[str]) -> list[str]:
    return [c for c in caps if is_known_capability(c)]
