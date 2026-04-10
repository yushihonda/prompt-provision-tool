from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class AccountType(str, enum.Enum):
    """アカウントタイプ"""
    PARENT = "PARENT"  # 親アカウント（管理者）
    CHILD = "CHILD"    # 子アカウント（外部ユーザー）


class ExecutionMode(str, enum.Enum):
    """実行モード"""
    SERVER = "server"              # サーバー実行（従来）
    LOCAL_PROXY = "local_proxy"    # ローカルワーカー → サーバー代理 LLM 実行
    LOCAL_DIRECT = "local_direct"  # ローカルワーカー → 直接 LLM 実行


class ModelType(str, enum.Enum):
    """AIモデルタイプ"""
    GPT4 = "gpt-4"
    GPT4_TURBO = "gpt-4-turbo-preview"
    GPT5_PRO = "gpt-5-pro"
    GPT5 = "gpt-5"
    GPT5_1 = "gpt-5.1"
    GPT5_1_THINKING = "gpt-5.1-thinking"
    GPT5_2 = "gpt-5.2"
    GPT5_2_PRO = "gpt-5.2-pro"
    GPT5_2_THINKING = "gpt-5.2-thinking"
    GEMINI_PRO = "gemini-pro"
    GEMINI_3_PRO = "gemini-3-pro-preview"
    GEMINI_3_PRO_DEEP_THINK = "gemini-3-pro-preview-deep-think"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_PRO_DEEP_THINK = "gemini-2.5-pro-deep-think"


class Account(Base):
    """アカウントテーブル"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    account_type = Column(String(20), nullable=False, default=AccountType.CHILD)
    is_active = Column(Boolean, default=True, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    total_cost = Column(Numeric(12, 6), default=0.0, nullable=False)
    total_executions = Column(Integer, default=0, nullable=False)
    tokens_this_month = Column(Integer, default=0, nullable=False)
    cost_this_month = Column(Numeric(12, 6), default=0.0, nullable=False)
    executions_this_month = Column(Integer, default=0, nullable=False)
    last_month_reset = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    skills_created = relationship("Skill", back_populates="creator", foreign_keys="Skill.created_by")
    account_skills = relationship("AccountSkill", back_populates="account", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="account", cascade="all, delete-orphan")
    api_config = relationship("APIConfig", back_populates="account", uselist=False, cascade="all, delete-orphan")
    daily_execution_counts = relationship("DailyExecutionCount", back_populates="account", cascade="all, delete-orphan")


class Skill(Base):
    """スキルテーブル（暗号化保存）"""
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    encrypted_content = Column(Text, nullable=False)  # 暗号化されたスキル内容
    model_type = Column(String(100), nullable=False)
    input_schema = Column(Text)  # JSON形式で入力フィールドの定義を保存
    # スキルレベルのデフォルト設定用 JSON。execution_config (StepExecutionConfig) を保持し、
    # スキル単独実行時もワークフロー内実行時もデフォルトランタイム (HTTP / external CLI) を宣言可能。
    config_json = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    allows_file_output = Column(Boolean, default=False, nullable=False)
    enable_deep_think = Column(Boolean, default=True, nullable=False)
    default_agent_profile = Column(String(30), nullable=True)
    created_by = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # リレーション
    creator = relationship("Account", back_populates="skills_created", foreign_keys=[created_by])
    account_skills = relationship("AccountSkill", back_populates="skill", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="skill", cascade="all, delete-orphan")


class Workflow(Base):
    """ワークフローテーブル"""
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    input_schema = Column(Text, nullable=True)  # ワークフロー共通入力スキーマ（JSON形式）
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # 親スキルモード: 常に "required"（optional/disabled は廃止）
    parent_skill_mode = Column(String(20), nullable=False, default="required", server_default="required")
    # スーパーバイザーモード: "disabled" | "after_each_group" | "after_marked_groups"
    supervisor_mode = Column(String(20), nullable=False, default="disabled", server_default="disabled")

    # 親スキル (Parent Skill) — ワークフローに直接埋め込み
    encrypted_parent_content = Column(Text, nullable=True)
    parent_model_type = Column(String(100), nullable=True, default="gpt-4o")
    parent_enable_deep_think = Column(Boolean, default=True, nullable=False)

    # ワークフローレベルの execution_config デフォルト。グループ/スキル/ステップで
    # 上書きされない限り全ステップに適用。Skill.config_json と同じ JSON 形式。
    config_json = Column(Text, nullable=True)

    # リレーション
    creator = relationship("Account")
    groups = relationship("WorkflowGroup", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowGroup.group_order")
    skills = relationship("WorkflowSkill", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowGroup(Base):
    """ワークフロー内のグループ（直列/並列の実行単位）"""
    __tablename__ = "workflow_groups"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    group_order = Column(Integer, nullable=False)
    group_name = Column(String(255), nullable=True)
    execution_type = Column(String(20), nullable=False, default="serial")  # 'serial' | 'parallel'
    condition_expression = Column(Text, nullable=True)  # JSON: 条件分岐式
    skip_on_condition_fail = Column(Boolean, default=True, nullable=False, server_default="1")  # 条件不成立時スキップ
    # スーパーバイザー (Group完了後の中間レビュー)
    supervisor_prompt = Column(Text, nullable=True)  # 暗号化プロンプト
    supervisor_model = Column(String(100), nullable=True)
    # 動的タスク分解: "static" | "dynamic"
    dynamic_mode = Column(String(20), nullable=False, default="static", server_default="static")
    # ジャッジ (並列Group完了後の合議)
    judge_prompt = Column(Text, nullable=True)  # 暗号化プロンプト
    judge_model = Column(String(100), nullable=True)
    # グループレベルの execution_config デフォルト。Workflow と Skill の間の継承チェーンに位置する。
    # Skill.config_json / WorkflowSkill.config_json と同じ JSON 形式。
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    workflow = relationship("Workflow", back_populates="groups")
    skills = relationship("WorkflowSkill", back_populates="group", cascade="all, delete-orphan", order_by="WorkflowSkill.order_in_group")


class WorkflowSkill(Base):
    """ワークフロー内のスキル"""
    __tablename__ = "workflow_skills"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_order = Column(Integer, nullable=False)  # 全体での順序
    skill_name = Column(String(255))
    config_json = Column(Text)
    depends_on = Column(Text, nullable=True)

    # エラーリカバリ
    on_error = Column(String(20), nullable=False, default="stop", server_default="stop")  # 'stop' | 'skip' | 'retry'
    max_retries = Column(Integer, nullable=False, default=0, server_default="0")
    retry_delay_seconds = Column(Integer, nullable=False, default=5, server_default="5")

    # 明示的データマッピング
    input_mapping = Column(Text, nullable=True)  # JSON: {"target_field": "steps.<ws_id>.output"}
    output_key = Column(String(100), nullable=True)  # このステップの出力キー名

    # 品質ゲート (Reflection / 自己修正ループ)
    quality_gate_type = Column(String(20), nullable=False, default="disabled", server_default="disabled")  # "disabled" | "regex" | "json_schema" | "llm"
    quality_gate_prompt = Column(Text, nullable=True)  # LLMゲート用プロンプト or regex/jsonスキーマ
    quality_gate_model = Column(String(100), nullable=True)
    max_reflection_loops = Column(Integer, nullable=False, default=0, server_default="0")

    # ハンドオフ (条件付き引継ぎ)
    handoff_rules = Column(Text, nullable=True)  # JSON: [{"condition": {...}, "target_skill_id": int}]
    agent_profile = Column(String(30), nullable=True)

    # グループ所属
    group_id = Column(Integer, ForeignKey("workflow_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    order_in_group = Column(Integer, nullable=True)

    # リレーション
    workflow = relationship("Workflow", back_populates="skills")
    skill = relationship("Skill")
    group = relationship("WorkflowGroup", back_populates="skills")


class WorkflowExecution(Base):
    """ワークフロー実行テーブル"""
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    current_step = Column(Integer, nullable=True)
    total_steps = Column(Integer, nullable=False)
    global_input_data = Column(Text)
    per_skill_input_data = Column(Text)  # JSON: {workflow_skill_id: {field: value}}
    continuation_lock_version = Column(Integer, nullable=False, default=0, server_default="0")  # 楽観ロック
    blackboard_data = Column(Text(length=16777215), nullable=True)  # MEDIUMTEXT: 共有メモリ (Blackboard)
    dynamic_plan_data = Column(Text, nullable=True)  # JSON: 動的分解プラン
    current_stage = Column(String(30), nullable=True)
    final_verdict = Column(String(10), nullable=True)
    handoff_summary = Column(Text, nullable=True)  # JSON: UI/監査向け派生サマリー
    synthesis_log = Column(Text, nullable=True)  # JSON配列: coordinator synthesis events の時系列記録
    coordinator_plan_id = Column(String(64), nullable=True, index=True)  # 紐付く CoordinatorPlan.plan_id
    error_message = Column(Text)
    workflow_name_snapshot = Column(String(255), nullable=True)  # 実行時点のワークフロー名スナップショット
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # ── セッション層 ──
    session_id = Column(String(64), nullable=True, unique=True, index=True)
    session_status = Column(String(30), nullable=True)  # セッション状態 (initializing / running / waiting_approval / completed / failed 等)
    current_step_id = Column(String(64), nullable=True)  # 現在処理中の task_id
    resume_cursor = Column(Text, nullable=True)  # 再開位置 JSON: {step_id, attempt_no, position}
    runtime_bindings = Column(Text, nullable=True)  # ステップ別ランタイム情報 JSON: {step_id: {adapter_id, runtime, ...}}
    workspace_bindings = Column(Text, nullable=True)  # ステップ別ワークスペース情報 JSON: {step_id: {workspace_id, mode, path, status}}
    approval_summary = Column(Text, nullable=True)  # 承認サマリー JSON: {pending:[], granted:[], rejected:[]}
    artifact_refs = Column(Text, nullable=True)  # ステップ別アーティファクト参照 JSON: {step_id: [artifact_id]}

    # リレーション
    workflow = relationship("Workflow")
    account = relationship("Account")
    executions = relationship("Execution", back_populates="workflow_execution", order_by="Execution.skill_order")


class WorkflowMemory(Base):
    """ワークフロー × profile 単位の永続メモリ"""
    __tablename__ = "workflow_memories"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    profile = Column(String(30), nullable=False, default="default")
    memory_data = Column(Text(length=16777215), nullable=True)  # MEDIUMTEXT: 蓄積メモリ
    starter_seed = Column(Text, nullable=True)  # 初期 seed（初回のみ適用）
    seed_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workflow = relationship("Workflow")


class AccountSkill(Base):
    """アカウントとスキルの紐付けテーブル"""
    __tablename__ = "account_skills"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    account = relationship("Account", back_populates="account_skills")
    skill = relationship("Skill", back_populates="account_skills")


class Execution(Base):
    """実行ログテーブル"""
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True)
    workflow_execution_id = Column(Integer, ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True)
    workflow_skill_id = Column(Integer, ForeignKey("workflow_skills.id", ondelete="SET NULL"), nullable=True)
    skill_order = Column(Integer, nullable=True)  # ワークフロー内のスキル順序
    input_data = Column(Text(length=16777215))   # MEDIUMTEXT: ワークフロー後段で前ステップ出力を含むため
    output_data = Column(Text(length=16777215))  # MEDIUMTEXT: 長文出力対応
    model_used = Column(String(100))
    tokens_used = Column(Integer)
    cost = Column(Numeric(10, 6), nullable=True)
    execution_time = Column(Integer)  # ミリ秒
    status = Column(String(50))  # success, error, timeout, pending, processing, pending_local, cancelled
    error_message = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    reflection_loop = Column(Integer, nullable=False, default=0, server_default="0")  # 品質ゲートリフレクション回数
    execution_role = Column(String(30), nullable=True)  # null | "quality_gate" | "supervisor" | "debate_judge"
    execution_group_id = Column(Integer, nullable=True)  # ジャッジ/スーパーバイザー用: 対象グループID
    agent_profile = Column(String(30), nullable=True)
    enable_deep_think = Column(Boolean, nullable=True)
    output_format = Column(String(10), nullable=True, default="txt")
    skill_name_snapshot = Column(String(255), nullable=True)  # 実行時点のスキル名スナップショット
    dispatch_mode = Column(String(30), nullable=False, default="server")
    # ルーティング判定結果。ワーカー/デスクトップランタイムが実行パスを選択するために使用。
    # bundle エンドポイントが初回取得時に設定し、フロントエンドのポーリングループが
    # SSE ストリーミング (HTTP) と Tauri の consume_external_cli_bundle (CLI) を判別する。
    # 値: "http_provider" (デフォルト) | "external_cli" | "internal"
    execution_kind = Column(String(30), nullable=False, default="http_provider", server_default="http_provider")
    lease_token_hash = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), server_default=func.now())

    # リレーション
    account = relationship("Account", back_populates="executions")
    skill = relationship("Skill", back_populates="executions")
    workflow_execution = relationship("WorkflowExecution", back_populates="executions")
    workflow_skill = relationship("WorkflowSkill")


class APIConfig(Base):
    """子アカウントのAPI設定テーブル"""
    __tablename__ = "api_configs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False)
    openai_api_key = Column(Text)  # Fernet暗号化後は長くなるためText
    gemini_api_key = Column(Text)  # Fernet暗号化後は長くなるためText
    anthropic_api_key = Column(Text)  # Fernet暗号化後は長くなるためText
    rate_limit_per_hour = Column(Integer, default=100)
    rate_limit_per_day = Column(Integer, default=1000)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # リレーション
    account = relationship("Account", back_populates="api_config")


class DailyExecutionCount(Base):
    """日ごとの実行回数テーブル"""
    __tablename__ = "daily_execution_counts"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    count = Column(Integer, nullable=False, server_default="0")

    # リレーション
    account = relationship("Account", back_populates="daily_execution_counts")


class CoordinatorPlan(Base):
    """Coordinator が実行前に生成する事前計画スナップショット
    複雑度・タスク・ロール・provider policy などを保持し、
    実行を観測する基準として使う (実行を駆動するわけではない)。
    """
    __tablename__ = "coordinator_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID
    workflow_execution_id = Column(Integer, ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    goal = Column(Text, nullable=True)
    complexity_level = Column(String(20), nullable=False, default="medium")  # low | medium | high
    max_parallelism = Column(Integer, nullable=False, default=4)
    roles = Column(Text, nullable=True)  # JSON: RoleSpec[]
    tasks = Column(Text(length=16777215), nullable=True)  # JSON: TaskSpec[]
    artifact_policy = Column(Text, nullable=True)  # JSON
    review_policy = Column(Text, nullable=True)  # JSON
    stop_conditions = Column(Text, nullable=True)  # JSON
    provider_policy = Column(Text, nullable=True)  # JSON: ProviderPolicy
    schema_version = Column(String(20), nullable=False, default="1.0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workflow_execution = relationship("WorkflowExecution")


class CoordinatorArtifact(Base):
    """Coordinator が管理する成果物 (Execution の出力を構造化して保持)
    artifact_type で notes / draft / review / score / final などを区別する。
    """
    __tablename__ = "coordinator_artifacts"

    id = Column(Integer, primary_key=True, index=True)
    artifact_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(64), nullable=False, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id", ondelete="SET NULL"), nullable=True)
    role = Column(String(30), nullable=False)  # researcher | writer | reviewer | judge
    artifact_type = Column(String(30), nullable=False)  # notes | evidence | draft | review | score | final
    schema_version = Column(String(20), nullable=False, default="1.0")
    summary = Column(Text, nullable=True)
    inline_content = Column(Text(length=16777215), nullable=True)  # MEDIUMTEXT
    content_ref = Column(Text, nullable=True)
    provider_mode = Column(String(30), nullable=True)  # remote_only | local_only | local_preferred | hybrid_auto
    model_hint = Column(String(100), nullable=True)
    extra_metadata = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("CoordinatorPlan")
    execution = relationship("Execution")


class CoordinatorWorker(Base):
    """名前付きの論理ワーカー
    実際の実行は Tauri 側の OrchestrationManager (worker pool) が担い、
    本テーブルは「どの role の誰がどのタスクを担当しているか」を表す投影。
    観測・可視化・将来の特定ワーカーへの割当に使う。
    """
    __tablename__ = "coordinator_workers"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # "researcher-1", "writer-A" 等
    role = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="idle")  # idle | running | blocked | failed | done
    task_queue = Column(Text, nullable=True)  # JSON: task_id[]
    artifact_refs = Column(Text, nullable=True)  # JSON: artifact_id[]
    provider_mode = Column(String(30), nullable=True)
    current_task_id = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("CoordinatorPlan")


class CoordinatorFollowUpTask(Base):
    """既存タスクの output を参照して発行する派生タスク
    parent_task_id があれば派生関係、なければ独立。
    reason は clarify / expand / fix / verify / merge を想定。
    """
    __tablename__ = "coordinator_followup_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    parent_task_id = Column(String(64), nullable=True, index=True)
    target_role = Column(String(30), nullable=False)
    target_worker_name = Column(String(100), nullable=True)
    objective = Column(Text, nullable=False)
    input_artifact_refs = Column(Text, nullable=True)  # JSON: artifact_id[]
    output_schema = Column(Text, nullable=True)
    requires_review = Column(Boolean, default=False, nullable=False)
    reason = Column(String(30), nullable=True)  # clarify | expand | fix | verify | merge
    status = Column(String(20), nullable=False, default="pending")  # pending | running | done | failed | cancelled
    depends_on = Column(Text, nullable=True)  # JSON: task_id[]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    plan = relationship("CoordinatorPlan")


class CoordinatorAdapter(Base):
    """coordinator が呼び出せる実行バックエンドのレジストリ
    internal_sidecar / local_llm / remote_api / external_cli の4種類を統一管理する。
    role と provider_mode で検索可能。
    """
    __tablename__ = "coordinator_adapters"

    id = Column(Integer, primary_key=True, index=True)
    adapter_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID
    name = Column(String(100), nullable=False, unique=True)  # human readable
    adapter_type = Column(String(30), nullable=False)  # internal | external_cli | hybrid | local_llm | remote_api
    provider_mode = Column(String(30), nullable=False)  # remote_only | local_only | local_preferred | hybrid_auto
    transport = Column(String(30), nullable=False, default="process_stdio")  # process_stdio | http | pty
    runtime = Column(String(50), nullable=True)  # python | node | binary | http
    impl = Column(String(255), nullable=True)  # 実装識別子（モジュール名/バイナリパス/エンドポイントURL等）
    supported_roles = Column(Text, nullable=True)  # JSON: role[]
    capabilities = Column(Text, nullable=True)  # JSON: ["streaming","files","tools",...]
    input_schema = Column(Text, nullable=True)  # JSON Schema
    output_schema = Column(Text, nullable=True)  # JSON Schema
    config = Column(Text, nullable=True)  # JSON: adapter固有設定
    is_enabled = Column(Boolean, default=True, nullable=False)
    health_status = Column(String(20), nullable=True)  # healthy | degraded | down | unknown
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ── アダプタハードニング ──
    risk_level = Column(String(20), nullable=True)  # リスクレベル (low / medium / high / critical)
    requires_workspace = Column(Boolean, nullable=True, server_default="0")  # ワークスペース必須フラグ
    default_approval_policy = Column(String(30), nullable=True)  # デフォルト承認ポリシー (ask_before_shell / allow_shell 等)
    auth_mechanism = Column(String(30), nullable=True)  # 認証方式 (none / api_key / oauth / local_session)
    supported_capabilities = Column(Text, nullable=True)  # capability 配列 (JSON)


class CoordinatorEvalRun(Base):
    """品質評価ハーネスのランレコード
    plan の完成度・修正率・local 利用率などのメトリクスを時系列で記録する。
    """
    __tablename__ = "coordinator_eval_runs"

    id = Column(Integer, primary_key=True, index=True)
    eval_id = Column(String(64), nullable=False, unique=True, index=True)
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_execution_id = Column(Integer, nullable=True, index=True)
    completeness = Column(Numeric(5, 2), nullable=True)  # 0-100
    factuality = Column(Numeric(5, 2), nullable=True)
    revision_rate = Column(Numeric(5, 2), nullable=True)
    judge_pass_rate = Column(Numeric(5, 2), nullable=True)
    overhead_ms = Column(Integer, nullable=True)
    artifact_reuse_rate = Column(Numeric(5, 2), nullable=True)
    local_usage_rate = Column(Numeric(5, 2), nullable=True)
    remote_escalation_rate = Column(Numeric(5, 2), nullable=True)
    metrics_extra = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("CoordinatorPlan")


class CoordinatorWorkspace(Base):
    """worker ごとに分離されたワークスペースのメタデータ
    coding 系 task で安全に並列作業できるようにするための分離単位。
    実体（ディレクトリ等）はクライアント側 (Tauri) で管理し、
    バックエンドはメタデータと promote/cleanup の状態のみ保持する。
    """
    __tablename__ = "coordinator_workspaces"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id = Column(String(64), nullable=True, index=True)
    task_id = Column(String(64), nullable=True, index=True)
    mode = Column(String(20), nullable=False, default="temp_dir")  # shared | temp_dir | worktree
    workspace_path = Column(Text, nullable=True)  # クライアント側で確定後に書き戻す
    cleanup_on_finish = Column(Boolean, default=True, nullable=False)
    promoted = Column(Boolean, default=False, nullable=False)  # promote 済みか
    status = Column(String(20), nullable=False, default="reserved")  # reserved | active | promoted | cleaned
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    cleaned_at = Column(DateTime(timezone=True), nullable=True)

    plan = relationship("CoordinatorPlan")


class CoordinatorEvent(Base):
    """Coordinator のオーケストレーションイベントログ
    plan_created / task_finished / artifact_created / judge_decision_made など
    coordinator 層で発生する全イベントを時系列で記録する。
    """
    __tablename__ = "coordinator_events"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    # plan_created | task_enqueued | task_started | task_finished
    # | artifact_created | review_requested | judge_decision_made | run_completed
    task_id = Column(String(64), nullable=True, index=True)
    artifact_id = Column(String(64), nullable=True)
    payload = Column(Text(length=16777215), nullable=True)  # JSON
    schema_version = Column(String(20), nullable=False, default="1.0")
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # ── 正規化イベント列 ──
    session_id = Column(String(64), nullable=True, index=True)  # 紐付くセッション ID
    step_id = Column(String(64), nullable=True, index=True)  # 対象ステップ ID
    event_seq = Column(Integer, nullable=True)  # セッション内の連番
    event_namespace = Column(String(30), nullable=True, index=True)  # イベント名前空間 (workflow / step / runtime / workspace / approval / artifact)

    plan = relationship("CoordinatorPlan")


class ApprovalRequest(Base):
    """承認リクエストテーブル (ask_before_shell 等の durable 承認ゲート)"""
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    approval_id = Column(String(64), nullable=False, unique=True, index=True)
    session_id = Column(String(64), nullable=True, index=True)  # 紐付くセッション
    plan_id = Column(String(64), ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"), nullable=True, index=True)
    step_id = Column(String(64), nullable=True, index=True)  # 対象ステップ
    execution_id = Column(Integer, ForeignKey("executions.id", ondelete="SET NULL"), nullable=True)
    workflow_execution_id = Column(Integer, ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=True, index=True)
    adapter_id = Column(String(64), nullable=True)  # 対象アダプタ
    runtime = Column(String(30), nullable=True)  # 対象ランタイム
    approval_policy = Column(String(30), nullable=False)  # 適用ポリシー
    status = Column(String(20), nullable=False, server_default="pending")  # 承認状態 (pending / granted / rejected / timed_out)
    prompt_preview = Column(Text, nullable=True)  # プロンプトのプレビュー
    cwd = Column(Text, nullable=True)  # 実行ディレクトリ
    decided_by = Column(String(100), nullable=True)  # 応答者
    decided_at = Column(DateTime(timezone=True), nullable=True)  # 応答日時
    attempt_no = Column(Integer, nullable=False, server_default="1")  # 同一ステップの試行回数
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("CoordinatorPlan")


class WorkerAPIKey(Base):
    """ローカルワーカー認証用APIキーテーブル"""
    __tablename__ = "worker_api_keys"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # リレーション
    account = relationship("Account")
