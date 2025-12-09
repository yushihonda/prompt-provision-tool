"""add_enable_deep_think_to_prompts

Revision ID: 40d79017ca9d
Revises: 000
Create Date: 2025-11-22 13:20:13.868330

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '40d79017ca9d'
down_revision = '000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # promptsテーブルにenable_deep_thinkカラムを追加
    op.add_column('prompts', sa.Column('enable_deep_think', sa.Boolean(), nullable=False, server_default='1'))


def downgrade() -> None:
    # enable_deep_thinkカラムを削除
    op.drop_column('prompts', 'enable_deep_think')

