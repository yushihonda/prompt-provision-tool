"""Supervisor / judge review action tests."""
from __future__ import annotations

import asyncio
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
from app.tasks.execution_tasks import _merge_blackboard  # noqa: E402
from app.api.user import get_workflow_execution_status, list_my_executions  # noqa: E402
from app.services.completion_service import trigger_workflow_continuation  # noqa: E402
from app.tasks.execution_tasks import (  # noqa: E402
    REVIEW_ACTION_APPROVE,
    REVIEW_ACTION_REPEAT_GROUP,
    _build_skill_input,
    _handle_supervisor_result,
    _parse_group_review_action,
)

SessionLocal = _database.SessionLocal


class GroupReviewActionTests(unittest.TestCase):
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
        self.group = WorkflowGroup(id=1, workflow_id=1, group_order=1, execution_type="parallel")
        self.group2 = WorkflowGroup(id=2, workflow_id=1, group_order=2, execution_type="parallel")
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
        )
        self.ws2 = WorkflowSkill(
            id=2,
            workflow_id=1,
            skill_id=1,
            group_id=1,
            skill_order=2,
            order_in_group=2,
            skill_name="Verify",
        )
        self.wf_exec = WorkflowExecution(
            id=1,
            workflow_id=1,
            account_id=1,
            status="processing",
            total_steps=2,
        )
        self.exec = Execution(
            id=1,
            account_id=1,
            skill_id=1,
            workflow_execution_id=1,
            workflow_skill_id=1,
            skill_order=1,
            input_data="{}",
            output_data="done",
            status="success",
            dispatch_mode="local",
        )
        self.exec2 = Execution(
            id=2,
            account_id=1,
            skill_id=1,
            workflow_execution_id=1,
            workflow_skill_id=2,
            skill_order=2,
            input_data="{}",
            output_data="done2",
            status="success",
            dispatch_mode="local",
        )
        self.db.add_all([
            self.account,
            self.workflow,
            self.group,
            self.group2,
            self.skill,
            self.ws,
            self.ws2,
            self.wf_exec,
            self.exec,
            self.exec2,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_parse_group_review_action_maps_legacy_repeat(self):
        parsed = _parse_group_review_action(json.dumps({"action": "repeat", "reason": "insufficient"}))
        self.assertEqual(parsed["action"], REVIEW_ACTION_REPEAT_GROUP)
        self.assertEqual(parsed["critique"], "insufficient")

    def test_parse_group_review_action_maps_continue_to_approve(self):
        parsed = _parse_group_review_action(json.dumps({"action": "continue"}))
        self.assertEqual(parsed["action"], REVIEW_ACTION_APPROVE)

    def test_parse_group_review_action_preserves_target_step_ids(self):
        parsed = _parse_group_review_action(json.dumps({
            "action": "repeat_group",
            "critique": "redo targeted steps",
            "target_step_ids": [2, "3", None, ""],
        }))
        self.assertEqual(parsed["action"], REVIEW_ACTION_REPEAT_GROUP)
        self.assertEqual(parsed["target_step_ids"], ["2", "3"])

    def test_parse_group_review_action_maps_goto_step_and_required_fixes(self):
        parsed = _parse_group_review_action(json.dumps({
            "action": "goto",
            "reason": "return to verifier",
            "goto_step_id": 2,
            "required_fixes": ["add assertions", "tighten verdict"],
        }))
        self.assertEqual(parsed["action"], "revise")
        self.assertEqual(parsed["goto_step_id"], "2")
        self.assertEqual(parsed["target_step_ids"], ["2"])
        self.assertEqual(parsed["required_fixes"], ["add assertions", "tighten verdict"])

    def test_supervisor_stop_marks_workflow_error(self):
        sv_execution = type("SvExec", (), {
            "output_data": json.dumps({"action": "stop", "reason": "needs rewrite"}),
            "execution_group_id": 1,
            "skill_order": 1,
        })()

        _handle_supervisor_result(self.db, self.wf_exec, sv_execution)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.wf_exec.status, "error")
        self.assertIn("needs rewrite", self.wf_exec.error_message or "")

    def test_supervisor_repeat_targets_only_selected_steps(self):
        sv_execution = type("SvExec", (), {
            "output_data": json.dumps({
                "action": "repeat_group",
                "critique": "rerun verifier only",
                "target_step_ids": [2],
            }),
            "execution_group_id": 1,
            "skill_order": 2,
        })()

        _handle_supervisor_result(self.db, self.wf_exec, sv_execution)
        self.db.refresh(self.exec)
        self.db.refresh(self.exec2)

        self.assertEqual(self.exec.status, "success")
        self.assertEqual(self.exec2.status, "cancelled")

    def test_supervisor_goto_step_id_targets_selected_step(self):
        sv_execution = type("SvExec", (), {
            "output_data": json.dumps({
                "action": "goto",
                "reason": "return to verifier",
                "goto_step_id": 2,
                "required_fixes": ["add assertions"],
            }),
            "execution_group_id": 1,
            "skill_order": 2,
        })()

        _handle_supervisor_result(self.db, self.wf_exec, sv_execution)
        self.db.refresh(self.exec)
        self.db.refresh(self.exec2)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.exec.status, "success")
        self.assertEqual(self.exec2.status, "cancelled")
        blackboard = json.loads(self.wf_exec.blackboard_data)
        self.assertEqual(blackboard["supervisor_group_1"]["goto_step_id"], "2")
        self.assertEqual(blackboard["supervisor_group_1"]["required_fixes"], ["add assertions"])

    def test_build_skill_input_includes_group_review_feedback(self):
        structured_context = {
            "blackboard": {
                "supervisor_group_1": {
                    "action": "repeat_group",
                    "critique": "rewrite the implementation",
                    "raw_output": "{}",
                    "target_step_ids": ["1"],
                    "required_fixes": ["fix summary"],
                },
                "judge_group_1": {
                    "action": "revise",
                    "critique": "choose the stronger branch",
                    "raw_output": "{}",
                },
            }
        }
        skill_input = _build_skill_input(
            self.ws,
            structured_context,
            {"topic": "x"},
            "",
            {},
            [],
        )
        self.assertIn("_nexmagi_review_feedback", skill_input)
        self.assertEqual(len(skill_input["_nexmagi_review_feedback"]), 2)
        critiques = [item["critique"] for item in skill_input["_nexmagi_review_feedback"]]
        self.assertIn("rewrite the implementation", critiques)
        self.assertIn("choose the stronger branch", critiques)
        supervisor_feedback = next(
            item for item in skill_input["_nexmagi_review_feedback"]
            if item["source_key"] == "supervisor_group_1"
        )
        self.assertEqual(supervisor_feedback["target_step_ids"], ["1"])
        self.assertEqual(supervisor_feedback["required_fixes"], ["fix summary"])

    def test_build_skill_input_includes_targeted_feedback_for_matching_step(self):
        _merge_blackboard(self.db, self.wf_exec, "supervisor_group_1", {
            "action": "repeat_group",
            "critique": "only rerun verifier",
            "raw_output": "{}",
            "target_step_ids": ["2"],
        })
        structured_context = {"blackboard": json.loads(self.wf_exec.blackboard_data)}

        skill_input = _build_skill_input(
            self.ws2,
            structured_context,
            {"topic": "x"},
            "",
            {},
            [],
        )

        self.assertEqual(skill_input["_nexmagi_review_feedback"][0]["target_step_ids"], ["2"])

    def test_build_skill_input_skips_targeted_feedback_for_non_matching_step(self):
        _merge_blackboard(self.db, self.wf_exec, "supervisor_group_1", {
            "action": "repeat_group",
            "critique": "only rerun verifier",
            "raw_output": "{}",
            "target_step_ids": ["2"],
        })
        structured_context = {"blackboard": json.loads(self.wf_exec.blackboard_data)}

        skill_input = _build_skill_input(
            self.ws,
            structured_context,
            {"topic": "x"},
            "",
            {},
            [],
        )

        self.assertNotIn("_nexmagi_review_feedback", skill_input)

    def test_launch_continuation_includes_required_fixes(self):
        structured_context = {
            "blackboard": {
                "supervisor_group_1": {
                    "action": "revise",
                    "critique": "return to verifier",
                    "raw_output": "{}",
                    "target_step_ids": ["2"],
                    "goto_step_id": "2",
                    "required_fixes": ["add assertions", "tighten verdict"],
                },
            }
        }

        skill_input = _build_skill_input(
            self.ws2,
            structured_context,
            {"topic": "x"},
            "",
            {},
            [],
        )

        latest_feedback = skill_input["_nexmagi_review_feedback"][-1]
        delta_instruction = f"レビュー差し戻しにより再実行されました。指摘: {latest_feedback['critique']}。必須修正: " + " / ".join(latest_feedback["required_fixes"])
        self.assertEqual(latest_feedback["goto_step_id"], "2")
        self.assertEqual(latest_feedback["required_fixes"], ["add assertions", "tighten verdict"])
        self.assertIn("必須修正", delta_instruction)

    def test_judge_stop_marks_workflow_error(self):
        judge_execution = Execution(
            id=3,
            account_id=1,
            workflow_execution_id=1,
            skill_order=1,
            input_data="{}",
            output_data=json.dumps({"action": "stop", "critique": "parallel outputs conflict"}),
            status="success",
            dispatch_mode="local",
            execution_role="debate_judge",
            execution_group_id=1,
        )
        self.db.add(judge_execution)
        self.db.commit()

        trigger_workflow_continuation(judge_execution, self.db)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.wf_exec.status, "error")
        self.assertIn("parallel outputs conflict", self.wf_exec.error_message or "")

    def test_judge_manual_review_sets_manual_review_required(self):
        judge_execution = Execution(
            id=4,
            account_id=1,
            workflow_execution_id=1,
            skill_order=2,
            input_data="{}",
            output_data=json.dumps({
                "action": "manual_review",
                "critique": "need a human decision",
                "required_fixes": ["compare both branches"],
            }),
            status="success",
            dispatch_mode="local",
            execution_role="debate_judge",
            execution_group_id=1,
        )
        self.db.add(judge_execution)
        self.db.commit()

        trigger_workflow_continuation(judge_execution, self.db)
        self.db.refresh(self.wf_exec)

        self.assertEqual(self.wf_exec.status, "manual_review_required")
        self.assertIn("need a human decision", self.wf_exec.error_message or "")

    def test_workflow_status_includes_review_feedback(self):
        self.wf_exec.blackboard_data = json.dumps({
            "judge_group_1": {
                "action": "manual_review",
                "critique": "need a human decision",
                "target_step_ids": ["2"],
                "goto_step_id": "2",
                "required_fixes": ["compare both branches"],
            }
        })
        self.db.add(self.wf_exec)
        self.db.commit()

        payload = asyncio.run(get_workflow_execution_status(
            1,
            db=self.db,
            current_user=self.account,
        ))

        self.assertEqual(payload["review_feedback"][0]["goto_step_id"], "2")
        self.assertEqual(payload["review_feedback"][0]["required_fixes"], ["compare both branches"])

    def test_list_my_executions_includes_workflow_execution_status(self):
        self.wf_exec.status = "manual_review_required"
        self.db.add(self.wf_exec)
        self.db.commit()

        payload = asyncio.run(list_my_executions(
            skip=0,
            limit=10,
            db=self.db,
            current_user=self.account,
        ))

        self.assertEqual(payload["items"][0]["workflow_execution_status"], "manual_review_required")


if __name__ == "__main__":
    unittest.main()
