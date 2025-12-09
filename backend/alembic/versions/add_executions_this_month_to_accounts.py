"""add_executions_this_month_to_accounts

Revision ID: add_executions_this_month
Revises: add_monthly_tokens_cost
Create Date: 2025-12-09 11:25:13.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = 'add_executions_this_month'
down_revision = 'create_api_configs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accountsテーブルに今月の実行回数カラムを追加
    op.add_column('accounts', sa.Column('executions_this_month', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    # executions_this_monthカラムを削除
    op.drop_column('accounts', 'executions_this_month')

