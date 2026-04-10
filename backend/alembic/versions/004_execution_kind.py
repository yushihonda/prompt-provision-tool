"""Add execution_kind to executions for frontend dispatch routing.

Surfaces the routing decision (http_provider / external_cli / internal)
on the Execution row so the frontend polling loop can choose between
SSE streaming and Tauri's consume_external_cli_bundle path. Default
is http_provider so legacy rows behave identically.

Revision ID: 004
Down revision: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "execution_kind",
                sa.String(length=30),
                nullable=False,
                server_default="http_provider",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("executions") as batch_op:
        batch_op.drop_column("execution_kind")
