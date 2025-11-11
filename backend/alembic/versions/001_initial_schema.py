"""initial schema

Revision ID: 001
Revises:
Create Date: 2024-10-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accounts テーブル
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('account_type', sa.Enum('parent', 'child', name='accounttype'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_accounts_username', 'accounts', ['username'], unique=True)
    op.create_index('ix_accounts_email', 'accounts', ['email'], unique=True)
    op.create_index('ix_accounts_id', 'accounts', ['id'], unique=False)

    # prompts テーブル
    op.create_table(
        'prompts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('encrypted_content', sa.Text(), nullable=False),
        sa.Column('model_type', sa.Enum('gpt-4', 'gpt-4-turbo-preview', 'gpt-5-pro', 'gemini-pro', 'gemini-2.5-pro', 'gemini-2.5-pro-deep-think', name='modeltype'), nullable=False),
        sa.Column('input_schema', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['created_by'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_prompts_name', 'prompts', ['name'], unique=False)
    op.create_index('ix_prompts_id', 'prompts', ['id'], unique=False)

    # account_prompts テーブル
    op.create_table(
        'account_prompts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('prompt_id', sa.Integer(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prompt_id'], ['prompts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # executions テーブル
    op.create_table(
        'executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('prompt_id', sa.Integer(), nullable=True),
        sa.Column('input_data', sa.Text(), nullable=True),
        sa.Column('output_data', sa.Text(), nullable=True),
        sa.Column('model_used', sa.String(length=100), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=True),
        sa.Column('execution_time', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prompt_id'], ['prompts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # api_configs テーブル
    op.create_table(
        'api_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('openai_api_key', sa.String(length=255), nullable=True),
        sa.Column('gemini_api_key', sa.String(length=255), nullable=True),
        sa.Column('rate_limit_per_hour', sa.Integer(), nullable=True, server_default='100'),
        sa.Column('rate_limit_per_day', sa.Integer(), nullable=True, server_default='1000'),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id')
    )


def downgrade() -> None:
    op.drop_table('api_configs')
    op.drop_table('executions')
    op.drop_table('account_prompts')
    op.drop_index('ix_prompts_id', table_name='prompts')
    op.drop_index('ix_prompts_name', table_name='prompts')
    op.drop_table('prompts')
    op.drop_index('ix_accounts_id', table_name='accounts')
    op.drop_index('ix_accounts_email', table_name='accounts')
    op.drop_index('ix_accounts_username', table_name='accounts')
    op.drop_table('accounts')

