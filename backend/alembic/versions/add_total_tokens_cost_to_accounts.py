"""add_total_tokens_cost_to_accounts

Revision ID: add_total_tokens_cost
Revises: a1b2c3d4e5f6
Create Date: 2025-11-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = 'add_total_tokens_cost'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accountsテーブルにtotal_tokensとtotal_costカラムを追加
    op.add_column('accounts', sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('total_cost', sa.Numeric(12, 6), nullable=False, server_default='0.0'))


def downgrade() -> None:
    # total_tokensとtotal_costカラムを削除
    op.drop_column('accounts', 'total_cost')
    op.drop_column('accounts', 'total_tokens')

