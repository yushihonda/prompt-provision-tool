"""add_tool_flags_to_prompts

Revision ID: 001_add_tool_flags_to_prompts
Revises: 000
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "001_add_tool_flags_to_prompts"
down_revision = "000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """プロンプトに外部ツール利用フラグ列を追加"""
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "enable_web_search",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "enable_code_interpreter",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "enable_file_search",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    # 既存レコードのデフォルト値をFalseに統一した後、サーバーデフォルトを削除
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.alter_column(
            "enable_web_search",
            server_default=None,
        )
        batch_op.alter_column(
            "enable_code_interpreter",
            server_default=None,
        )
        batch_op.alter_column(
            "enable_file_search",
            server_default=None,
        )


def downgrade() -> None:
    """外部ツール利用フラグ列を削除"""
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.drop_column("enable_web_search")
        batch_op.drop_column("enable_code_interpreter")
        batch_op.drop_column("enable_file_search")


