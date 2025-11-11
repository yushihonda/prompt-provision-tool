"""relax enums to string for model_type and account_type

Revision ID: 002
Revises: 001
Create Date: 2025-11-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # prompts.model_type を ENUM から VARCHAR(100) へ
    with op.batch_alter_table('prompts') as batch_op:
        batch_op.alter_column('model_type',
                              existing_type=sa.Enum('gpt-4', 'gpt-4-turbo-preview', 'gpt-5-pro', 'gemini-pro', 'gemini-2.5-pro', 'gemini-2.5-pro-deep-think', name='modeltype'),
                              type_=sa.String(length=100),
                              nullable=False)

    # accounts.account_type を ENUM から VARCHAR(20) へ
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('account_type',
                              existing_type=sa.Enum('parent', 'child', name='accounttype'),
                              type_=sa.String(length=20),
                              nullable=False)


def downgrade() -> None:
    # 可能な範囲で元に戻す（注意: 既存データによっては失敗する可能性あり）
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('account_type',
                              existing_type=sa.String(length=20),
                              type_=sa.Enum('parent', 'child', name='accounttype'),
                              nullable=False)

    with op.batch_alter_table('prompts') as batch_op:
        batch_op.alter_column('model_type',
                              existing_type=sa.String(length=100),
                              type_=sa.Enum('gpt-4', 'gpt-4-turbo-preview', 'gpt-5-pro', 'gemini-pro', 'gemini-2.5-pro', 'gemini-2.5-pro-deep-think', name='modeltype'),
                              nullable=False)


