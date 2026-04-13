"""Add config_json to skills for skill-level execution_config defaults.

Free-form JSON column mirroring WorkflowSkill.config_json. Holds
`execution_config` (StepExecutionConfig) so a skill can declare its
default runtime (HTTP provider vs external CLI) independent of the
workflow step that wraps it. Nullable; legacy rows behave identically
to before (treated as default/legacy execution_config).

Revision ID: 002
Down revision: 001
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("skills") as batch_op:
        batch_op.add_column(sa.Column("config_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("skills") as batch_op:
        batch_op.drop_column("config_json")
