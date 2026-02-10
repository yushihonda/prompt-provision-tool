"""add_workflow_execution_and_sequential_execution

Revision ID: 003_add_workflow_execution_and_sequential_execution
Revises: 002_add_workflows_and_workflow_skills
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003_add_workflow_execution_and_sequential_execution"
down_revision = "002_add_workflows_and_workflow_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """WorkflowExecutionテーブルを追加し、Executionテーブルにワークフロー関連カラムを追加"""
    
    # WorkflowExecutionテーブルを作成
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("global_input_data", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    
    # Executionテーブルにワークフロー関連カラムを追加
    op.add_column("executions", sa.Column("workflow_execution_id", sa.Integer(), sa.ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True))
    op.add_column("executions", sa.Column("workflow_skill_id", sa.Integer(), sa.ForeignKey("workflow_skills.id", ondelete="SET NULL"), nullable=True))
    op.add_column("executions", sa.Column("step_order", sa.Integer(), nullable=True))
    
    # インデックスを追加
    op.create_index("ix_executions_workflow_execution_id", "executions", ["workflow_execution_id"])


def downgrade() -> None:
    """WorkflowExecutionテーブルを削除し、Executionテーブルからワークフロー関連カラムを削除"""
    
    # インデックスを削除
    op.drop_index("ix_executions_workflow_execution_id", table_name="executions")
    
    # Executionテーブルからワークフロー関連カラムを削除
    op.drop_column("executions", "step_order")
    op.drop_column("executions", "workflow_skill_id")
    op.drop_column("executions", "workflow_execution_id")
    
    # WorkflowExecutionテーブルを削除
    op.drop_table("workflow_executions")

