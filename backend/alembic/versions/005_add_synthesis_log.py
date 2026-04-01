"""WorkflowExecution に synthesis_log カラムを追加

coordinator view / synthesis events の記録用。
JSON配列としてイベントを時系列で保存する。

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column("synthesis_log", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_executions", "synthesis_log")
