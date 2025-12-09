"""create_api_configs_for_existing_accounts

Revision ID: create_api_configs
Revises: ec41999f179f
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'create_api_configs'
down_revision = 'add_monthly_tokens_cost'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    既存の子アカウントに対してAPI設定を自動作成
    """
    # 既存の子アカウント（CHILDタイプ）でAPI設定が存在しないアカウントに対して
    # デフォルトのAPI設定を作成
    connection = op.get_bind()
    
    # 子アカウントでAPI設定が存在しないアカウントを取得してAPI設定を作成
    connection.execute(text("""
        INSERT INTO api_configs (account_id, rate_limit_per_hour, rate_limit_per_day, is_enabled, created_at)
        SELECT 
            a.id,
            100,
            1000,
            TRUE,
            NOW()
        FROM accounts a
        WHERE a.account_type = 'CHILD'
        AND NOT EXISTS (
            SELECT 1 
            FROM api_configs ac 
            WHERE ac.account_id = a.id
        )
    """))


def downgrade() -> None:
    """
    このマイグレーションで作成されたAPI設定を削除
    （既存のAPI設定も削除される可能性があるため、注意が必要）
    """
    # 注意: このダウングレードは、このマイグレーションで作成されたAPI設定のみを削除するものではありません
    # すべてのAPI設定を削除する場合は、以下のコメントを解除してください
    # op.execute("DELETE FROM api_configs")
    pass

