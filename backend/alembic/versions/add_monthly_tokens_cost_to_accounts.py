"""add_monthly_tokens_cost_to_accounts

Revision ID: add_monthly_tokens_cost
Revises: add_total_tokens_cost
Create Date: 2025-11-23 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = 'add_monthly_tokens_cost'
down_revision = 'add_total_tokens_cost'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accountsテーブルに今月のトークン数、料金、月リセット日時カラムを追加
    op.add_column('accounts', sa.Column('tokens_this_month', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('cost_this_month', sa.Numeric(12, 6), nullable=False, server_default='0.0'))
    op.add_column('accounts', sa.Column('last_month_reset', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # カラムを削除
    op.drop_column('accounts', 'last_month_reset')
    op.drop_column('accounts', 'cost_this_month')
    op.drop_column('accounts', 'tokens_this_month')

