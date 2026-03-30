"""
統合マイグレーション: 全テーブルを最終スキーマで作成

旧マイグレーション 000〜007 を統合し、用語リネーム（Prompt→Skill）を反映。

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

    # ==================== skills (旧 prompts) ====================
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
        sa.Column("enable_web_search", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enable_code_interpreter", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enable_file_search", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ==================== account_skills (旧 account_prompts) ====================
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
        # 親スキル (Parent Skill) — ワークフローに直接埋め込み
        sa.Column("encrypted_parent_content", sa.Text(), nullable=True),
        sa.Column("parent_model_type", sa.String(100), nullable=True, server_default="gpt-5.1"),
        sa.Column("parent_enable_deep_think", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("parent_enable_web_search", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("parent_enable_code_interpreter", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("parent_enable_file_search", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    # ==================== workflow_groups ====================
    op.create_table(
        "workflow_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("group_order", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=True),
        sa.Column("execution_type", sa.String(20), nullable=False, server_default="serial"),
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
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ==================== api_configs ====================
    op.create_table(
        "api_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("openai_api_key", sa.Text(), nullable=True),
        sa.Column("gemini_api_key", sa.Text(), nullable=True),
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


def downgrade() -> None:
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
