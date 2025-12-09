"""add_cost_to_executions

Revision ID: add_cost_to_executions
Revises: ec41999f179f
Create Date: 2025-11-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'ec41999f179f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # executionsテーブルにcostカラムを追加（トークン料金、USD、小数点以下6桁まで）
    op.add_column('executions', sa.Column('cost', sa.Numeric(10, 6), nullable=True))


def downgrade() -> None:
    # costカラムを削除
    op.drop_column('executions', 'cost')

