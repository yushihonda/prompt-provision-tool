"""add_workflows_and_workflow_skills

Revision ID: 002_add_workflows_and_workflow_skills
Revises: 001_add_tool_flags_to_prompts
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "002_add_workflows_and_workflow_skills"
down_revision = "001_add_tool_flags_to_prompts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Workflow / WorkflowSkill テーブルを追加"""
    op.create_table(
        "workflows",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=255), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "workflow_skills",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=255), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Workflow / WorkflowSkill テーブルを削除"""
    op.drop_table("workflow_skills")
    op.drop_table("workflows")


