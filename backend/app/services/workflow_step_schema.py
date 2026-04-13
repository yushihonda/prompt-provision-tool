"""ワークフローステップの実行メタデータスキーマ

`WorkflowSkill.config_json` の `execution_config` キー内に格納される。
`config_json` は既存の自由形式 Text 列なので DB マイグレーション不要。

レガシー行 (`execution_config` キーなし) はデフォルト設定として解釈され、
従来の HTTP/internal プロバイダ経路 + read_only 承認 + ワークスペースなし
で動作する。既存のワークフロー定義には一切影響しない。
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
    """`execution` ブロック — ランタイムとアダプタの選択。"""
    model_config = ConfigDict(extra="allow")

    execution_kind: ExecutionKind = "auto"
    preferred_adapter: Optional[str] = None
    candidate_adapters: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    cli_runtime_hint: Optional[str] = None  # "claude_code" | "codex" | "generic"
    cwd_hint: Optional[str] = None
    # CLI 専用: 外部 CLI バイナリに渡すモデル ID
    # (例: "claude-sonnet-4-6", "gpt-5-codex")
    # プロバイダランタイムでは無視される（プロバイダは親 Skill 行の model_type を使用）
    cli_model: Optional[str] = None


class StepWorkspaceMeta(BaseModel):
    """`workspace` ブロック — ワークスペースライフサイクル設定。"""
    model_config = ConfigDict(extra="allow")

    workspace_policy: WorkspacePolicy = "none"
    share_with_steps: list[str] = Field(default_factory=list)
    promote_on: Literal["accepted", "always", "never"] = "accepted"
    cleanup_on: Literal["failed", "discarded", "always", "never"] = "failed"


class StepApprovalMeta(BaseModel):
    """`approval` ブロック — ステップ実行時の権限制御。"""
    model_config = ConfigDict(extra="allow")

    policy: ApprovalPolicy = "read_only"
    allow_writes: bool = False
    allow_shell: bool = False


class StepArtifactContract(BaseModel):
    """`artifact_contract` ブロック — 期待される出力形式のヒント。"""
    model_config = ConfigDict(extra="allow")

    expected_type: Optional[str] = None
    must_include_files: bool = False
    must_include_diff: bool = False


class StepExecutionConfig(BaseModel):
    """ワークフローステップの実行メタデータ全体。

    `WorkflowSkill.config_json` の `execution_config` キーに JSON として永続化。
    前方互換: 各階層の未知キーは保持される (extra='allow')。
    """
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    execution: StepExecutionMeta = Field(default_factory=StepExecutionMeta)
    workspace: StepWorkspaceMeta = Field(default_factory=StepWorkspaceMeta)
    approval: StepApprovalMeta = Field(default_factory=StepApprovalMeta)
    artifact_contract: StepArtifactContract = Field(default_factory=StepArtifactContract)


def default_step_execution_config() -> StepExecutionConfig:
    """レガシー互換のデフォルト設定を返す。

    `execution_config` キーのない行はこの設定と同じ動作になる:
    auto ルーティング / ワークスペースなし / read_only 承認。
    """
    return StepExecutionConfig()


def parse_execution_config(raw_config_json: Any) -> StepExecutionConfig:
    """config_json (文字列 or dict) を読み取り、正規化した StepExecutionConfig を返す。

    以下の場合はすべてデフォルト + 警告ログ:
    - 値が None または空
    - JSON として不正
    - `execution_config` キーが存在しない
    - スキーマバリデーション失敗
    """
    if raw_config_json is None or raw_config_json == "":
        return default_step_execution_config()

    if isinstance(raw_config_json, (bytes, bytearray)):
        raw_config_json = raw_config_json.decode("utf-8", errors="replace")

    if isinstance(raw_config_json, str):
        try:
            data = json.loads(raw_config_json)
        except json.JSONDecodeError as e:
            logger.warning("config_json が有効な JSON ではありません: %s", e)
            return default_step_execution_config()
    elif isinstance(raw_config_json, dict):
        data = raw_config_json
    else:
        logger.warning("config_json の型が想定外です: %s", type(raw_config_json).__name__)
        return default_step_execution_config()

    exec_config = data.get("execution_config")
    if not isinstance(exec_config, dict):
        # レガシー行 — execution_config ブロックなし
        return default_step_execution_config()

    try:
        return StepExecutionConfig.model_validate(exec_config)
    except ValidationError as e:
        logger.warning("execution_config のスキーマバリデーション失敗、デフォルトにフォールバック: %s", e)
        return default_step_execution_config()


def merge_execution_config_into_config_json(
    raw_config_json: Any,
    new_execution_config: StepExecutionConfig,
) -> str:
    """既存の config_json に新しい execution_config をマージする。

    他のキーは保持したまま、execution_config のみ上書きする。
    書き戻し用の JSON 文字列を返す。
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


def merge_step_execution_config_chain(
    *configs: Optional[StepExecutionConfig],
) -> StepExecutionConfig:
    """StepExecutionConfig を左から右へ順にマージする。

    Workflow → WorkflowGroup → Skill → WorkflowSkill の継承チェーンで使用。
    後の設定が前の設定をブロック単位で上書きする。
    None やデフォルト相当のエントリは何も寄与しない。
    """
    result: Optional[StepExecutionConfig] = None
    for cfg in configs:
        if cfg is None:
            continue
        result = merge_step_execution_configs(result, cfg)
    return result if result is not None else default_step_execution_config()


def merge_step_execution_configs(
    parent: Optional[StepExecutionConfig],
    override: Optional[StepExecutionConfig],
) -> StepExecutionConfig:
    """親 (スキルレベルデフォルト) と子 (ステップレベル) の設定をブロック単位でマージする。

    ポリシー:
    - override のブロックがデフォルトと異なる場合、ブロック全体を置換（フィールド単位の深いマージはしない）
    - それ以外は親のブロックを保持
    - schema_version は override 優先、なければ親

    ブロック単位の置換により「execution_kind=external_cli を設定したのに
    親の workspace_policy=shared が暗黙的に引き継がれる」という微妙なバグを防ぐ。
    """
    if parent is None:
        parent = default_step_execution_config()
    if override is None:
        override = default_step_execution_config()
    default = default_step_execution_config()

    def _block_set(override_block, default_block) -> bool:
        return override_block.model_dump() != default_block.model_dump()

    merged_execution = (
        override.execution if _block_set(override.execution, default.execution)
        else parent.execution
    )
    merged_workspace = (
        override.workspace if _block_set(override.workspace, default.workspace)
        else parent.workspace
    )
    merged_approval = (
        override.approval if _block_set(override.approval, default.approval)
        else parent.approval
    )
    merged_artifact = (
        override.artifact_contract
        if _block_set(override.artifact_contract, default.artifact_contract)
        else parent.artifact_contract
    )

    return StepExecutionConfig(
        schema_version=override.schema_version or parent.schema_version,
        execution=merged_execution,
        workspace=merged_workspace,
        approval=merged_approval,
        artifact_contract=merged_artifact,
    )


def is_legacy_step(config: StepExecutionConfig) -> bool:
    """レガシーデフォルトと区別がつかないか判定する。

    何も明示設定されていない場合に True を返す。
    ルーティングで既存パスへのショートカットに使用。
    """
    default = default_step_execution_config()
    return config.model_dump() == default.model_dump()
