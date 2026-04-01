"""workflow_memories テーブルを追加

ワークフロー × agent_profile 単位の永続メモリ。
実行をまたいで蓄積される補助記憶。

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"


def upgrade() -> None:
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
