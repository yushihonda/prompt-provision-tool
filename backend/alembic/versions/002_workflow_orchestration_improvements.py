"""
ワークフローオーケストレーション改善

- WorkflowSkill: エラーリカバリ(on_error, max_retries, retry_delay_seconds), input_mapping, output_key
- WorkflowGroup: 条件分岐(condition_expression, skip_on_condition_fail)
- WorkflowExecution: 楽観ロック(continuation_lock_version)
- Workflow: 親スキルモード(parent_skill_mode)
- Execution: リトライカウント(retry_count)

Revision ID: 002
Down revision: 001
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- workflow_skills ---
    op.add_column("workflow_skills", sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("workflow_skills", sa.Column("retry_delay_seconds", sa.Integer(), nullable=False, server_default=sa.text("5")))
    op.add_column("workflow_skills", sa.Column("on_error", sa.String(20), nullable=False, server_default="stop"))
    op.add_column("workflow_skills", sa.Column("input_mapping", sa.Text(), nullable=True))
    op.add_column("workflow_skills", sa.Column("output_key", sa.String(100), nullable=True))

    # --- workflow_groups ---
    op.add_column("workflow_groups", sa.Column("condition_expression", sa.Text(), nullable=True))
    op.add_column("workflow_groups", sa.Column("skip_on_condition_fail", sa.Boolean(), nullable=False, server_default=sa.text("1")))

    # --- workflow_executions ---
    op.add_column("workflow_executions", sa.Column("continuation_lock_version", sa.Integer(), nullable=False, server_default=sa.text("0")))

    # --- workflows ---
    op.add_column("workflows", sa.Column("parent_skill_mode", sa.String(20), nullable=False, server_default="required"))

    # --- executions ---
    op.add_column("executions", sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("executions", "retry_count")
    op.drop_column("workflows", "parent_skill_mode")
    op.drop_column("workflow_executions", "continuation_lock_version")
    op.drop_column("workflow_groups", "skip_on_condition_fail")
    op.drop_column("workflow_groups", "condition_expression")
    op.drop_column("workflow_skills", "output_key")
    op.drop_column("workflow_skills", "input_mapping")
    op.drop_column("workflow_skills", "on_error")
    op.drop_column("workflow_skills", "retry_delay_seconds")
    op.drop_column("workflow_skills", "max_retries")
