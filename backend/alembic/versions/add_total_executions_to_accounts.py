"""add_total_executions_to_accounts

Revision ID: add_total_executions
Revises: add_executions_this_month
Create Date: 2025-12-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'add_total_executions'
down_revision = 'add_executions_this_month'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accountsテーブルに総実行回数カラムを追加
    op.add_column('accounts', sa.Column('total_executions', sa.Integer(), nullable=False, server_default='0'))
    
    # 既存のExecutionレコードから集計して初期値を設定
    connection = op.get_bind()
    connection.execute(text("""
        UPDATE accounts 
        SET total_executions = (
            SELECT COUNT(*) 
            FROM executions 
            WHERE executions.account_id = accounts.id
        )
    """))


def downgrade() -> None:
    # total_executionsカラムを削除
    op.drop_column('accounts', 'total_executions')

