"""Workflow step execution metadata schema.

Lives inside `WorkflowSkill.config_json` under the `execution_config`
key. No DB migration — `config_json` is already a free-form Text column.

Legacy step rows (no `execution_config` key) are interpreted as the
default config, which routes through the existing HTTP/internal
provider path with read-only approval and no workspace. This means
adding the schema does NOT change behavior for any currently-defined
workflow.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

ExecutionKind = Literal["provider", "external_cli", "auto"]
WorkspacePolicy = Literal["none", "shared", "temp_dir", "worktree"]
ApprovalPolicy = Literal["read_only", "ask_before_shell", "allow_shell", "allow_write"]


class StepExecutionMeta(BaseModel):
    """`execution` block — picks runtime + adapter."""
    model_config = ConfigDict(extra="allow")

    execution_kind: ExecutionKind = "auto"
    preferred_adapter: Optional[str] = None
    candidate_adapters: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    cli_runtime_hint: Optional[str] = None  # "claude_code" | "codex" | "generic"
    cwd_hint: Optional[str] = None


class StepWorkspaceMeta(BaseModel):
    """`workspace` block — workspace lifecycle preferences."""
    model_config = ConfigDict(extra="allow")

    workspace_policy: WorkspacePolicy = "none"
    share_with_steps: list[str] = Field(default_factory=list)
    promote_on: Literal["accepted", "always", "never"] = "accepted"
    cleanup_on: Literal["failed", "discarded", "always", "never"] = "failed"


class StepApprovalMeta(BaseModel):
    """`approval` block — what the step is allowed to do at runtime."""
    model_config = ConfigDict(extra="allow")

    policy: ApprovalPolicy = "read_only"
    allow_writes: bool = False
    allow_shell: bool = False


class StepArtifactContract(BaseModel):
    """`artifact_contract` block — informational hint about expected output."""
    model_config = ConfigDict(extra="allow")

    expected_type: Optional[str] = None
    must_include_files: bool = False
    must_include_diff: bool = False


class StepExecutionConfig(BaseModel):
    """Full execution metadata for a workflow step.

    Persisted as JSON inside `WorkflowSkill.config_json` under
    `execution_config`. Forward-compatible: unknown keys at any level
    are preserved (extra='allow').
    """
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    execution: StepExecutionMeta = Field(default_factory=StepExecutionMeta)
    workspace: StepWorkspaceMeta = Field(default_factory=StepWorkspaceMeta)
    approval: StepApprovalMeta = Field(default_factory=StepApprovalMeta)
    artifact_contract: StepArtifactContract = Field(default_factory=StepArtifactContract)


def default_step_execution_config() -> StepExecutionConfig:
    """Return the legacy-equivalent default config.

    A row without `execution_config` should produce identical behavior
    to before this PR: auto routing, no workspace, read_only approval.
    """
    return StepExecutionConfig()


def parse_execution_config(raw_config_json: Any) -> StepExecutionConfig:
    """Read a `WorkflowSkill.config_json` value (string or dict) and
    return the normalized `StepExecutionConfig`.

    Failure modes (all return default + log warning):
    - raw is None or empty
    - raw is not valid JSON
    - raw is JSON but has no `execution_config` key
    - `execution_config` is malformed against the schema
    """
    if raw_config_json is None or raw_config_json == "":
        return default_step_execution_config()

    if isinstance(raw_config_json, (bytes, bytearray)):
        raw_config_json = raw_config_json.decode("utf-8", errors="replace")

    if isinstance(raw_config_json, str):
        try:
            data = json.loads(raw_config_json)
        except json.JSONDecodeError as e:
            logger.warning("workflow_skill config_json is not valid JSON: %s", e)
            return default_step_execution_config()
    elif isinstance(raw_config_json, dict):
        data = raw_config_json
    else:
        logger.warning(
            "workflow_skill config_json has unexpected type %s",
            type(raw_config_json).__name__,
        )
        return default_step_execution_config()

    exec_config = data.get("execution_config")
    if not isinstance(exec_config, dict):
        # Legacy row — no execution_config block at all.
        return default_step_execution_config()

    try:
        return StepExecutionConfig.model_validate(exec_config)
    except ValidationError as e:
        logger.warning(
            "workflow_skill execution_config failed schema validation, falling back to default: %s",
            e,
        )
        return default_step_execution_config()


def merge_execution_config_into_config_json(
    raw_config_json: Any,
    new_execution_config: StepExecutionConfig,
) -> str:
    """Update an existing `config_json` blob with a new
    `execution_config` while preserving every other key.

    Returns the merged JSON string ready to write back to the column.
    """
    base: dict[str, Any]
    if raw_config_json is None or raw_config_json == "":
        base = {}
    elif isinstance(raw_config_json, str):
        try:
            loaded = json.loads(raw_config_json)
            base = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            base = {}
    elif isinstance(raw_config_json, dict):
        base = dict(raw_config_json)
    else:
        base = {}

    base["execution_config"] = new_execution_config.model_dump(mode="json")
    return json.dumps(base, ensure_ascii=False)


def is_legacy_step(config: StepExecutionConfig) -> bool:
    """True if this config is indistinguishable from the legacy default
    (i.e. nothing was set explicitly). Used by routing to short-circuit
    to the existing path.
    """
    default = default_step_execution_config()
    return config.model_dump() == default.model_dump()
