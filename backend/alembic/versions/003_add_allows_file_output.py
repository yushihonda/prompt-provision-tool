"""add allows_file_output to prompts

Revision ID: 003
Revises: 002
Create Date: 2025-11-09 13:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # promptsテーブルにallows_file_outputカラムを追加
    op.add_column('prompts', sa.Column('allows_file_output', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    # allows_file_outputカラムを削除
    op.drop_column('prompts', 'allows_file_output')

