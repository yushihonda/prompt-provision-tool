"""
次世代AIオーケストレーションパターン

- Reflection: 品質ゲート + 自己修正ループ
- Blackboard: 共有メモリ
- Supervisor: グループ間監視・ルーティング
- Dynamic Decomposition: 動的タスク分解
- Debate/Judge: 並列結果の合議
- Handoff: 条件付き引継ぎ

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
    # --- workflow_skills: Reflection ---
    op.add_column("workflow_skills", sa.Column("quality_gate_prompt", sa.Text(), nullable=True))
    op.add_column("workflow_skills", sa.Column("quality_gate_model", sa.String(100), nullable=True))
    op.add_column("workflow_skills", sa.Column("quality_gate_type", sa.String(20), nullable=False, server_default="disabled"))
    op.add_column("workflow_skills", sa.Column("max_reflection_loops", sa.Integer(), nullable=False, server_default=sa.text("0")))
    # --- workflow_skills: Handoff ---
    op.add_column("workflow_skills", sa.Column("handoff_rules", sa.Text(), nullable=True))

    # --- workflow_groups: Supervisor ---
    op.add_column("workflow_groups", sa.Column("supervisor_prompt", sa.Text(), nullable=True))
    op.add_column("workflow_groups", sa.Column("supervisor_model", sa.String(100), nullable=True))
    # --- workflow_groups: Dynamic ---
    op.add_column("workflow_groups", sa.Column("dynamic_mode", sa.String(20), nullable=False, server_default="static"))
    # --- workflow_groups: Judge ---
    op.add_column("workflow_groups", sa.Column("judge_prompt", sa.Text(), nullable=True))
    op.add_column("workflow_groups", sa.Column("judge_model", sa.String(100), nullable=True))

    # --- workflow_executions: Blackboard + Dynamic ---
    op.add_column("workflow_executions", sa.Column("blackboard_data", sa.Text(), nullable=True))
    op.add_column("workflow_executions", sa.Column("dynamic_plan_data", sa.Text(), nullable=True))

    # --- workflows: Supervisor ---
    op.add_column("workflows", sa.Column("supervisor_mode", sa.String(20), nullable=False, server_default="disabled"))

    # --- executions: Reflection + Role + Group ---
    op.add_column("executions", sa.Column("reflection_loop", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("executions", sa.Column("execution_role", sa.String(30), nullable=True))
    op.add_column("executions", sa.Column("execution_group_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("executions", "execution_group_id")
    op.drop_column("executions", "execution_role")
    op.drop_column("executions", "reflection_loop")
    op.drop_column("workflows", "supervisor_mode")
    op.drop_column("workflow_executions", "dynamic_plan_data")
    op.drop_column("workflow_executions", "blackboard_data")
    op.drop_column("workflow_groups", "judge_model")
    op.drop_column("workflow_groups", "judge_prompt")
    op.drop_column("workflow_groups", "dynamic_mode")
    op.drop_column("workflow_groups", "supervisor_model")
    op.drop_column("workflow_groups", "supervisor_prompt")
    op.drop_column("workflow_skills", "handoff_rules")
    op.drop_column("workflow_skills", "max_reflection_loops")
    op.drop_column("workflow_skills", "quality_gate_type")
    op.drop_column("workflow_skills", "quality_gate_model")
    op.drop_column("workflow_skills", "quality_gate_prompt")
