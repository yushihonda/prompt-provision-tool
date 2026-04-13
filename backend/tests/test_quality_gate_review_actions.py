"""Quality gate review action handling tests."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

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
    Base,
    Execution,
    Skill,
    Workflow,
    WorkflowExecution,
    WorkflowGroup,
    WorkflowSkill,
)
from app.tasks.execution_tasks import (  # noqa: E402
    REVIEW_ACTION_MANUAL_REVIEW,
    REVIEW_ACTION_REVISE,
    REVIEW_ACTION_STOP,
    _handle_quality_gate_result,
    _parse_review_action,
)

SessionLocal = _database.SessionLocal


class QualityGateReviewActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=_test_engine)

    def setUp(self):
        self.db = SessionLocal()
        for model in (
            Execution,
            WorkflowSkill,
            WorkflowGroup,
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
        self.workflow = Workflow(id=1, name="wf", created_by=1)
        self.group = WorkflowGroup(id=1, workflow_id=1, group_order=1, execution_type="serial")
        self.skill = Skill(
            id=1,
            name="Verify target",
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
            skill_name="Verify target",
            max_reflection_loops=0,
        )
        self.wf_exec = WorkflowExecution(
            id=1,
            workflow_id=1,
            account_id=1,
            status="processing",
            total_steps=1,
        )
        self.db.add_all([self.account, self.workflow, self.group, self.skill, self.ws, self.wf_exec])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_parse_review_action_defaults_unstructured_to_revise(self):
        parsed = _parse_review_action("this should be revised")
        self.assertEqual(parsed["action"], REVIEW_ACTION_REVISE)

    def test_quality_gate_fail_with_no_reflection_stops_workflow(self):
        gate_execution = type("GateExec", (), {
            "output_data": json.dumps({"pass": False, "critique": "missing verdict"}),
            "workflow_skill_id": 1,
            "reflection_loop": 0,
            "skill_order": 1,
        })()

        _handle_quality_gate_result(self.db, self.wf_exec, gate_execution)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.wf_exec.status, "error")
        self.assertIn("missing verdict", self.wf_exec.error_message or "")

    def test_quality_gate_manual_review_action_stops_workflow(self):
        gate_execution = type("GateExec", (), {
            "output_data": json.dumps({"action": "manual_review", "critique": "needs human review"}),
            "workflow_skill_id": 1,
            "reflection_loop": 0,
            "skill_order": 1,
        })()

        _handle_quality_gate_result(self.db, self.wf_exec, gate_execution)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.wf_exec.status, "manual_review_required")
        self.assertIn("needs human review", self.wf_exec.error_message or "")
        self.assertIsNotNone(self.wf_exec.completed_at)

    def test_quality_gate_stop_action_stops_workflow(self):
        gate_execution = type("GateExec", (), {
            "output_data": json.dumps({"action": "stop", "critique": "blocked"}),
            "workflow_skill_id": 1,
            "reflection_loop": 0,
            "skill_order": 1,
        })()

        _handle_quality_gate_result(self.db, self.wf_exec, gate_execution)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.wf_exec.status, "error")
        self.assertIn("blocked", self.wf_exec.error_message or "")


if __name__ == "__main__":
    unittest.main()
