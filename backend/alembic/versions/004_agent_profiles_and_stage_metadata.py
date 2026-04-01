"""
agent profile / stage / verdict metadata

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
    op.add_column("skills", sa.Column("default_agent_profile", sa.String(length=30), nullable=True))
    op.add_column("workflow_skills", sa.Column("agent_profile", sa.String(length=30), nullable=True))
    op.add_column("workflow_executions", sa.Column("current_stage", sa.String(length=30), nullable=True))
    op.add_column("workflow_executions", sa.Column("final_verdict", sa.String(length=10), nullable=True))
    op.add_column("workflow_executions", sa.Column("handoff_summary", sa.Text(), nullable=True))
    op.add_column("executions", sa.Column("agent_profile", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("executions", "agent_profile")
    op.drop_column("workflow_executions", "handoff_summary")
    op.drop_column("workflow_executions", "final_verdict")
    op.drop_column("workflow_executions", "current_stage")
    op.drop_column("workflow_skills", "agent_profile")
    op.drop_column("skills", "default_agent_profile")
