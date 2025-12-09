"""add_deleted_at_to_prompts

Revision ID: add_deleted_at_to_prompts
Revises: add_total_executions
Create Date: 2025-12-09 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_deleted_at_to_prompts'
down_revision = 'add_total_executions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # promptsテーブルに論理削除用のdeleted_atカラムを追加
    op.add_column('prompts', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # deleted_atカラムを削除
    op.drop_column('prompts', 'deleted_at')

