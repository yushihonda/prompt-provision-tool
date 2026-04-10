"""WorkflowRunSession + 承認リクエスト + アダプタハードニングの統合マイグレーション

内容:
  1. workflow_executions: セッション列 (session_id, session_status,
     current_step_id, resume_cursor, ランタイム/ワークスペース/承認/アーティファクト
     の JSON バインディング)
  2. coordinator_events: 正規化イベント列 (session_id, step_id,
     event_seq, event_namespace)
  3. approval_requests テーブル: ask_before_shell の永続承認ライフサイクル
  4. coordinator_adapters: risk_level, requires_workspace,
     default_approval_policy, auth_mechanism, supported_capabilities

Revision ID: 005
Down revision: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. workflow_executions: セッション層 ──
    with op.batch_alter_table("workflow_executions") as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("session_status", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("current_step_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("resume_cursor", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("runtime_bindings", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("workspace_bindings", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("approval_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("artifact_refs", sa.Text(), nullable=True))
        batch_op.create_index("ix_wf_exec_session_id", ["session_id"], unique=True)

    # ── 2. coordinator_events: 正規化イベント列 ──
    with op.batch_alter_table("coordinator_events") as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("step_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("event_seq", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("event_namespace", sa.String(30), nullable=True))
        batch_op.create_index("ix_coord_evt_session_id", ["session_id"])
        batch_op.create_index("ix_coord_evt_step_id", ["step_id"])
        batch_op.create_index("ix_coord_evt_namespace", ["event_namespace"])

    # ── 3. approval_requests テーブル ──
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("approval_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("session_id", sa.String(64), nullable=True, index=True),
        sa.Column("plan_id", sa.String(64),
                  sa.ForeignKey("coordinator_plans.plan_id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("step_id", sa.String(64), nullable=True, index=True),
        sa.Column("execution_id", sa.Integer(),
                  sa.ForeignKey("executions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("workflow_execution_id", sa.Integer(),
                  sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("adapter_id", sa.String(64), nullable=True),
        sa.Column("runtime", sa.String(30), nullable=True),
        sa.Column("approval_policy", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("prompt_preview", sa.Text(), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_approval_req_session_step_attempt",
        "approval_requests",
        ["session_id", "step_id", "attempt_no"],
        unique=True,
    )

    # ── 4. coordinator_adapters: ハードニング列 ──
    with op.batch_alter_table("coordinator_adapters") as batch_op:
        batch_op.add_column(sa.Column("risk_level", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("requires_workspace", sa.Boolean(),
                                      nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("default_approval_policy", sa.String(30),
                                      nullable=True))
        batch_op.add_column(sa.Column("auth_mechanism", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("supported_capabilities", sa.Text(), nullable=True))


def downgrade() -> None:
    # 4. アダプタハードニング
    with op.batch_alter_table("coordinator_adapters") as batch_op:
        batch_op.drop_column("supported_capabilities")
        batch_op.drop_column("auth_mechanism")
        batch_op.drop_column("default_approval_policy")
        batch_op.drop_column("requires_workspace")
        batch_op.drop_column("risk_level")

    # 3. 承認リクエスト
    op.drop_index("ix_approval_req_session_step_attempt", table_name="approval_requests")
    op.drop_table("approval_requests")

    # 2. 正規化イベント列
    with op.batch_alter_table("coordinator_events") as batch_op:
        batch_op.drop_index("ix_coord_evt_namespace")
        batch_op.drop_index("ix_coord_evt_step_id")
        batch_op.drop_index("ix_coord_evt_session_id")
        batch_op.drop_column("event_namespace")
        batch_op.drop_column("event_seq")
        batch_op.drop_column("step_id")
        batch_op.drop_column("session_id")

    # 1. セッション層
    with op.batch_alter_table("workflow_executions") as batch_op:
        batch_op.drop_index("ix_wf_exec_session_id")
        batch_op.drop_column("artifact_refs")
        batch_op.drop_column("approval_summary")
        batch_op.drop_column("workspace_bindings")
        batch_op.drop_column("runtime_bindings")
        batch_op.drop_column("resume_cursor")
        batch_op.drop_column("current_step_id")
        batch_op.drop_column("session_status")
        batch_op.drop_column("session_id")
