"""add_enable_deep_think_to_executions

Revision ID: ec41999f179f
Revises: 40d79017ca9d
Create Date: 2025-11-22 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec41999f179f'
down_revision = '40d79017ca9d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # executionsテーブルにenable_deep_thinkカラムを追加（実行時点の状態を保存）
    op.add_column('executions', sa.Column('enable_deep_think', sa.Boolean(), nullable=True))


def downgrade() -> None:
    # enable_deep_thinkカラムを削除
    op.drop_column('executions', 'enable_deep_think')

