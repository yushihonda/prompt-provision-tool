"""Add config_json to workflows and workflow_groups for parent-level execution_config defaults.

Mirrors the JSON column already present on skills / workflow_skills, so
the full inheritance chain (workflow → group → skill → step) can carry
StepExecutionConfig blocks. Nullable; legacy rows behave identically to
before (treated as default/legacy execution_config).

Revision ID: 003
Down revision: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.add_column(sa.Column("config_json", sa.Text(), nullable=True))
    with op.batch_alter_table("workflow_groups") as batch_op:
        batch_op.add_column(sa.Column("config_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_groups") as batch_op:
        batch_op.drop_column("config_json")
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.drop_column("config_json")
