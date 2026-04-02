"""
統合マイグレーション: 全テーブルを最終スキーマで作成

旧マイグレーション 001〜006 を統合。
新規セットアップ時はこの1ファイルのみで全テーブルが作成される。

Revision ID: 001
Down revision: None (初期マイグレーション)
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==================== accounts ====================
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False, server_default="CHILD"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_cost", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("total_executions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tokens_this_month", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_this_month", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("executions_this_month", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_month_reset", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # ==================== skills ====================
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("model_type", sa.String(100), nullable=False),
        sa.Column("input_schema", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("allows_file_output", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enable_deep_think", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("default_agent_profile", sa.String(30), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ==================== account_skills ====================
    op.create_table(
        "account_skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ==================== workflows ====================
    op.create_table(
        "workflows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_schema", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # 親スキル
        sa.Column("encrypted_parent_content", sa.Text(), nullable=True),
        sa.Column("parent_model_type", sa.String(100), nullable=True, server_default="gpt-5.1"),
        sa.Column("parent_enable_deep_think", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("parent_skill_mode", sa.String(20), nullable=False, server_default="required"),
        sa.Column("supervisor_mode", sa.String(20), nullable=False, server_default="disabled"),
    )

    # ==================== workflow_groups ====================
    op.create_table(
        "workflow_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("group_order", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=True),
        sa.Column("execution_type", sa.String(20), nullable=False, server_default="serial"),
        sa.Column("condition_expression", sa.Text(), nullable=True),
        sa.Column("skip_on_condition_fail", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("supervisor_prompt", sa.Text(), nullable=True),
        sa.Column("supervisor_model", sa.String(100), nullable=True),
        sa.Column("dynamic_mode", sa.String(20), nullable=False, server_default="static"),
        sa.Column("judge_prompt", sa.Text(), nullable=True),
        sa.Column("judge_model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ==================== workflow_skills ====================
    op.create_table(
        "workflow_skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("skill_order", sa.Integer(), nullable=False),
        sa.Column("skill_name", sa.String(255), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("depends_on", sa.Text(), nullable=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("workflow_groups.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("order_in_group", sa.Integer(), nullable=True),
        sa.Column("on_error", sa.String(20), nullable=False, server_default="stop"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("input_mapping", sa.Text(), nullable=True),
        sa.Column("output_key", sa.String(100), nullable=True),
        sa.Column("quality_gate_type", sa.String(20), nullable=False, server_default="disabled"),
        sa.Column("quality_gate_prompt", sa.Text(), nullable=True),
        sa.Column("quality_gate_model", sa.String(100), nullable=True),
        sa.Column("max_reflection_loops", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("handoff_rules", sa.Text(), nullable=True),
        sa.Column("agent_profile", sa.String(30), nullable=True),
    )

    # ==================== workflow_executions ====================
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("global_input_data", sa.Text(), nullable=True),
        sa.Column("per_skill_input_data", sa.Text(), nullable=True),
        sa.Column("continuation_lock_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("blackboard_data", sa.Text(length=16777215), nullable=True),
        sa.Column("dynamic_plan_data", sa.Text(), nullable=True),
        sa.Column("current_stage", sa.String(30), nullable=True),
        sa.Column("final_verdict", sa.String(10), nullable=True),
        sa.Column("handoff_summary", sa.Text(), nullable=True),
        sa.Column("synthesis_log", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ==================== executions ====================
    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_execution_id", sa.Integer(), sa.ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("workflow_skill_id", sa.Integer(), sa.ForeignKey("workflow_skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_order", sa.Integer(), nullable=True),
        sa.Column("input_data", sa.Text(), nullable=True),
        sa.Column("output_data", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(10, 6), nullable=True),
        sa.Column("execution_time", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("enable_deep_think", sa.Boolean(), nullable=True),
        sa.Column("output_format", sa.String(10), nullable=True, server_default="txt"),
        sa.Column("dispatch_mode", sa.String(30), nullable=False, server_default="server"),
        sa.Column("lease_token_hash", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reflection_loop", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("execution_role", sa.String(30), nullable=True),
        sa.Column("execution_group_id", sa.Integer(), nullable=True),
        sa.Column("agent_profile", sa.String(30), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ==================== api_configs ====================
    op.create_table(
        "api_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("openai_api_key", sa.Text(), nullable=True),
        sa.Column("gemini_api_key", sa.Text(), nullable=True),
        sa.Column("anthropic_api_key", sa.Text(), nullable=True),
        sa.Column("rate_limit_per_hour", sa.Integer(), server_default=sa.text("100")),
        sa.Column("rate_limit_per_day", sa.Integer(), server_default=sa.text("1000")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # ==================== daily_execution_counts ====================
    op.create_table(
        "daily_execution_counts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # ==================== worker_api_keys ====================
    op.create_table(
        "worker_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ==================== workflow_memories ====================
    op.create_table(
        "workflow_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("profile", sa.String(30), nullable=False, server_default="default"),
        sa.Column("memory_data", sa.Text(length=16777215), nullable=True),
        sa.Column("starter_seed", sa.Text(), nullable=True),
        sa.Column("seed_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "profile", name="uq_workflow_profile_memory"),
    )


def downgrade() -> None:
    op.drop_table("workflow_memories")
    op.drop_table("worker_api_keys")
    op.drop_table("daily_execution_counts")
    op.drop_table("api_configs")
    op.drop_table("executions")
    op.drop_table("workflow_executions")
    op.drop_table("workflow_skills")
    op.drop_table("workflow_groups")
    op.drop_table("workflows")
    op.drop_table("account_skills")
    op.drop_table("skills")
    op.drop_table("accounts")
