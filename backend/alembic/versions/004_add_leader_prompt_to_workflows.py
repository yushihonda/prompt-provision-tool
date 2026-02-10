"""add_leader_prompt_to_workflows

Revision ID: 004_leader_pmt
Revises: 003_add_workfl
Create Date: 2026-01-09
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_leader_pmt"
down_revision = "003_add_workfl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Workflowごとに統合用プロンプト（leader_prompt_id）を持たせる"""
    op.add_column(
        "workflows",
        sa.Column(
            "leader_prompt_id",
            sa.Integer(),
            sa.ForeignKey("prompts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """leader_prompt_id カラムを削除"""
    op.drop_column("workflows", "leader_prompt_id")

