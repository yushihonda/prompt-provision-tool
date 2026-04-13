"""Plan approval gating flow tests."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used")
os.environ.setdefault("ENCRYPTION_KEY", "0" * 32)
os.environ["DEBUG"] = "0"

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import sqlalchemy  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as _database  # noqa: E402

_test_engine = sqlalchemy.create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}
)
_database.engine = _test_engine
_database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

from app.models import (  # noqa: E402
    Account,
    ApprovalRequest,
    Base,
    CoordinatorArtifact,
    CoordinatorPlan,
    Execution,
    Skill,
    Workflow,
    WorkflowExecution,
    WorkflowGroup,
    WorkflowSkill,
)
from app.api.user import (  # noqa: E402
    get_workflow_execution_approvals,
    resubmit_plan_approval,
    respond_to_approval,
)
from app.services.workflow_step_schema import (  # noqa: E402
    StepApprovalMeta,
    StepExecutionConfig,
    merge_execution_config_into_config_json,
)
from app.tasks.execution_tasks import _launch_skills  # noqa: E402

SessionLocal = _database.SessionLocal


def _plan_required_config_json() -> str:
    return merge_execution_config_into_config_json(
        {},
        StepExecutionConfig(
            approval=StepApprovalMeta(policy="plan_required"),
        ),
    )


def _create_plan_artifact(db, execution_id: int, approval_id: str) -> None:
    artifact = CoordinatorArtifact(
        artifact_id=f"art_{approval_id}",
        plan_id="plan_test",
        task_id="task_1",
        execution_id=execution_id,
        role="writer",
        artifact_type="draft",
        summary="Implement の実行計画確認",
        inline_content="ステップ: Implement",
        content_ref=f"approval:{approval_id}",
        extra_metadata=json.dumps({"artifact_subtype": "execution_plan", "status": "pending"}, ensure_ascii=False),
    )
    db.add(artifact)
    db.commit()


class PlanApprovalFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=_test_engine)

    def setUp(self):
        self.db = SessionLocal()
        for model in (
            ApprovalRequest,
            Execution,
            WorkflowSkill,
            WorkflowGroup,
            CoordinatorPlan,
            WorkflowExecution,
            Workflow,
            Skill,
            Account,
        ):
            self.db.query(model).delete()
        self.db.commit()

        self.account = Account(
            id=1,
            username="user1",
            email="user@example.com",
            hashed_password="x",
            account_type="CHILD",
        )
        self.workflow = Workflow(
            id=1,
            name="wf",
            created_by=1,
        )
        self.group = WorkflowGroup(
            id=1,
            workflow_id=1,
            group_order=1,
            execution_type="serial",
        )
        self.skill = Skill(
            id=1,
            name="Implement",
            encrypted_content="enc",
            model_type="gpt-5",
            created_by=1,
        )
        self.ws = WorkflowSkill(
            id=1,
            workflow_id=1,
            skill_id=1,
            group_id=1,
            skill_order=1,
            order_in_group=1,
            skill_name="Implement",
            config_json=_plan_required_config_json(),
        )
        self.wf_exec = WorkflowExecution(
            id=1,
            workflow_id=1,
            account_id=1,
            status="pending",
            total_steps=1,
            session_id="sess_test",
            session_status="running",
            coordinator_plan_id="plan_test",
        )
        self.plan = CoordinatorPlan(
            plan_id="plan_test",
            workflow_execution_id=1,
            goal="g",
            tasks=json.dumps([]),
        )
        self.db.add_all([
            self.account,
            self.workflow,
            self.group,
            self.skill,
            self.ws,
            self.wf_exec,
            self.plan,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_launch_skills_creates_pending_approval_execution_and_request(self):
        _launch_skills(
            self.db,
            self.wf_exec,
            [self.ws],
            structured_context={},
            global_input={},
            previous_output="",
            per_skill_input={},
        )

        execution = self.db.query(Execution).filter(Execution.workflow_execution_id == self.wf_exec.id).one()
        approval = self.db.query(ApprovalRequest).filter(ApprovalRequest.execution_id == execution.id).one()
        artifact = self.db.query(CoordinatorArtifact).filter(
            CoordinatorArtifact.content_ref == f"approval:{approval.approval_id}"
        ).one()

        self.assertEqual(execution.status, "pending_approval")
        self.assertEqual(approval.status, "pending")
        self.assertEqual(approval.approval_policy, "plan_required")
        self.assertEqual(approval.step_id, "task_1")
        self.assertEqual(artifact.summary, "Implement の実行計画確認")
        self.assertIn("agent_profile:", artifact.inline_content or "")
        self.assertIn("artifact_subtype", artifact.extra_metadata or "")

    def test_granted_plan_approval_promotes_execution_to_pending_local(self):
        execution = Execution(
            account_id=1,
            skill_id=1,
            workflow_execution_id=1,
            workflow_skill_id=1,
            skill_order=1,
            input_data="{}",
            status="pending_approval",
            dispatch_mode="local",
            execution_kind="external_cli",
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)

        approval = ApprovalRequest(
            approval_id="apr_plan_1",
            session_id="sess_test",
            plan_id="plan_test",
            step_id="task_1",
            execution_id=execution.id,
            workflow_execution_id=1,
            runtime="external_cli",
            approval_policy="plan_required",
            status="pending",
        )
        self.db.add(approval)
        self.db.commit()
        _create_plan_artifact(self.db, execution.id, "apr_plan_1")

        result = asyncio.run(
            respond_to_approval(
                wf_execution_id=1,
                approval_id="apr_plan_1",
                decision="granted",
                db=self.db,
                current_user=self.account,
            )
        )

        self.db.refresh(execution)
        self.assertEqual(result["status"], "granted")
        self.assertEqual(execution.status, "pending_local")
        artifact = self.db.query(CoordinatorArtifact).filter(
            CoordinatorArtifact.content_ref == "approval:apr_plan_1"
        ).one()
        self.assertIn("\"status\": \"granted\"", artifact.extra_metadata or "")

    def test_rejected_plan_approval_marks_execution_error_and_continues(self):
        execution = Execution(
            account_id=1,
            skill_id=1,
            workflow_execution_id=1,
            workflow_skill_id=1,
            skill_order=1,
            input_data="{}",
            status="pending_approval",
            dispatch_mode="local",
            execution_kind="external_cli",
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)

        approval = ApprovalRequest(
            approval_id="apr_plan_2",
            session_id="sess_test",
            plan_id="plan_test",
            step_id="task_1",
            execution_id=execution.id,
            workflow_execution_id=1,
            runtime="external_cli",
            approval_policy="plan_required",
            status="pending",
        )
        self.db.add(approval)
        self.db.commit()
        _create_plan_artifact(self.db, execution.id, "apr_plan_2")

        with patch("app.tasks.execution_tasks.continue_workflow_execution") as mocked_continue:
            result = asyncio.run(
                respond_to_approval(
                    wf_execution_id=1,
                    approval_id="apr_plan_2",
                    decision="rejected",
                    comment="もう少し具体的にしてください",
                    db=self.db,
                    current_user=self.account,
                )
            )

        self.db.refresh(execution)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(execution.status, "error")
        self.assertIn("Plan approval rejected", execution.error_message or "")
        mocked_continue.assert_called_once_with(1, 1)
        artifact = self.db.query(CoordinatorArtifact).filter(
            CoordinatorArtifact.content_ref == "approval:apr_plan_2"
        ).one()
        self.assertIn("decision_comment", artifact.extra_metadata or "")

    def test_get_approvals_includes_plan_artifact_payload(self):
        _launch_skills(
            self.db,
            self.wf_exec,
            [self.ws],
            structured_context={},
            global_input={},
            previous_output="",
            per_skill_input={},
        )
        payload = asyncio.run(
            get_workflow_execution_approvals(
                wf_execution_id=1,
                db=self.db,
                current_user=self.account,
            )
        )
        self.assertEqual(len(payload["approvals"]), 1)
        plan_artifact = payload["approvals"][0]["plan_artifact"]
        self.assertIsNotNone(plan_artifact)
        self.assertEqual(plan_artifact["summary"], "Implement の実行計画確認")
        self.assertIn("ステップ: Implement", plan_artifact["content"])

    def test_resubmit_plan_creates_new_pending_approval_and_artifact(self):
        execution = Execution(
            account_id=1,
            skill_id=1,
            workflow_execution_id=1,
            workflow_skill_id=1,
            skill_order=1,
            input_data="{}",
            status="error",
            error_message="Plan approval rejected by user",
            dispatch_mode="local",
            execution_kind="external_cli",
            model_used="gpt-5",
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)

        approval = ApprovalRequest(
            approval_id="apr_plan_3",
            session_id="sess_test",
            plan_id="plan_test",
            step_id="task_1",
            execution_id=execution.id,
            workflow_execution_id=1,
            runtime="external_cli",
            approval_policy="plan_required",
            status="rejected",
            attempt_no=1,
        )
        self.db.add(approval)
        self.db.commit()
        _create_plan_artifact(self.db, execution.id, "apr_plan_3")

        result = asyncio.run(
            resubmit_plan_approval(
                wf_execution_id=1,
                approval_id="apr_plan_3",
                updated_content="ステップ: Implement\n修正版プランです",
                updated_summary="Implement の修正版実行計画",
                db=self.db,
                current_user=self.account,
            )
        )

        self.db.refresh(execution)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(execution.status, "pending_approval")
        self.assertIsNone(execution.error_message)
        new_approval = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.approval_id == result["approval_id"]
        ).one()
        self.assertEqual(new_approval.attempt_no, 2)
        new_artifact = self.db.query(CoordinatorArtifact).filter(
            CoordinatorArtifact.content_ref == f"approval:{result['approval_id']}"
        ).one()
        self.assertEqual(new_artifact.summary, "Implement の修正版実行計画")
        self.assertIn("revision_count", new_artifact.extra_metadata or "")


if __name__ == "__main__":
    unittest.main()
