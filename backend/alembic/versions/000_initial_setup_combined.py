"""初回セットアップ用統合マイグレーション

本番環境・開発環境の初回セットアップ時に使用する統合マイグレーションファイル
以下の変更をすべて含む：
- 初期スキーマ作成（accounts, prompts, account_prompts, executions, api_configs）
- モデルタイプとアカウントタイプを文字列型で作成（ENUM型を使用しない）
- ファイル出力機能（allows_file_output）を含む
- Deep Think機能（enable_deep_think）を含む
- 実行コスト（cost）を含む
- アカウント統計（total_tokens, total_cost, tokens_this_month, cost_this_month, executions_this_month, total_executions）を含む
- 論理削除（deleted_at）を含む

注意: このファイルは新規環境の初回セットアップ専用です。
既存環境で使用する場合は、個別のマイグレーションファイルを使用してください。

Revision ID: 000
Revises: None
Create Date: 2025-12-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '000'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    初回セットアップ: すべてのテーブルを最新の状態で作成
    """
    # accounts テーブル
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('account_type', sa.String(length=20), nullable=False),  # ENUMではなく文字列型
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        # 統計カラム（全期間）
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_cost', sa.Numeric(12, 6), nullable=False, server_default='0.0'),
        sa.Column('total_executions', sa.Integer(), nullable=False, server_default='0'),
        # 統計カラム（今月）
        sa.Column('tokens_this_month', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_this_month', sa.Numeric(12, 6), nullable=False, server_default='0.0'),
        sa.Column('executions_this_month', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_month_reset', sa.DateTime(timezone=True), nullable=True),
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
        sa.Column('model_type', sa.String(length=100), nullable=False),  # ENUMではなく文字列型
        sa.Column('input_schema', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('allows_file_output', sa.Boolean(), nullable=False, server_default='0'),  # ファイル出力機能を含む
        sa.Column('enable_deep_think', sa.Boolean(), nullable=False, server_default='1'),  # Deep Think機能
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),  # 論理削除
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
        sa.Column('cost', sa.Numeric(10, 6), nullable=True),  # 実行コスト（USD、小数点以下6桁まで）
        sa.Column('execution_time', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('enable_deep_think', sa.Boolean(), nullable=True),  # 実行時点のDeep Think設定
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
    """
    すべてのテーブルを削除
    """
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
