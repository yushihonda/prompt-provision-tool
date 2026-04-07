"""Phase 4.3 — workspace allocation + share_with_steps."""
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
    Base,
    CoordinatorAdapter,
    CoordinatorPlan,
    CoordinatorWorkspace,
)
from app.services.coordinator_extensions import seed_default_adapters  # noqa: E402
from app.services.coordinator_service import (  # noqa: E402
    EXECUTION_KIND_EXTERNAL_CLI,
    ROLE_WRITER,
    cleanup_workspace,
    find_workspace_by_task_id,
    promote_workspace,
    resolve_execution_kind,
    update_workspace_path,
)
from app.services.workflow_step_schema import (  # noqa: E402
    StepApprovalMeta,
    StepExecutionConfig,
    StepExecutionMeta,
    StepWorkspaceMeta,
)

SessionLocal = _database.SessionLocal


def _make_plan(db, plan_id="plan-1") -> CoordinatorPlan:
    plan = CoordinatorPlan(
        plan_id=plan_id,
        workflow_execution_id=42,
        goal="test",
        tasks=json.dumps([]),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def _cli_step_config(workspace_policy="temp_dir", share_with_steps=None) -> StepExecutionConfig:
    return StepExecutionConfig(
        execution=StepExecutionMeta(
            execution_kind="external_cli",
            preferred_adapter="claude-code-local",
            cli_runtime_hint="claude_code",
        ),
        workspace=StepWorkspaceMeta(
            workspace_policy=workspace_policy,
            share_with_steps=share_with_steps or [],
        ),
        approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
    )


class WorkflowWorkspaceShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=_test_engine)

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(CoordinatorWorkspace).delete()
        self.db.query(CoordinatorAdapter).delete()
        self.db.query(CoordinatorPlan).delete()
        self.db.commit()
        seed_default_adapters(self.db)
        self.plan = _make_plan(self.db)

    def tearDown(self):
        self.db.close()

    def test_temp_dir_step_reserves_workspace(self):
        cfg = _cli_step_config()
        task = {
            "task_id": "code_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertIsNotNone(task.get("workspace_id"))
        self.assertEqual(task.get("workspace_mode"), "temp_dir")
        # Workspace row exists.
        ws = find_workspace_by_task_id(self.db, self.plan.plan_id, "code_step")
        self.assertIsNotNone(ws)
        self.assertEqual(ws.status, "reserved")
        # The bundle payload echoes the workspace id.
        payload = result["external_cli_payload"]
        self.assertEqual(payload["workspace_id"], task["workspace_id"])
        self.assertEqual(payload["workspace_mode"], "temp_dir")

    def test_share_with_steps_reuses_upstream_workspace(self):
        # Step 1: code step reserves a workspace.
        cfg_a = _cli_step_config()
        task_a = {
            "task_id": "code_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg_a,
        }
        resolve_execution_kind(self.db, self.plan, task_a)
        first_ws_id = task_a["workspace_id"]
        self.assertIsNotNone(first_ws_id)

        # Step 2: verify step shares with code_step.
        cfg_b = _cli_step_config(share_with_steps=["code_step"])
        task_b = {
            "task_id": "verify_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg_b,
        }
        resolve_execution_kind(self.db, self.plan, task_b)
        self.assertEqual(task_b["workspace_id"], first_ws_id)
        self.assertEqual(task_b.get("_workspace_shared_from"), "code_step")

    def test_share_with_steps_falls_back_to_new_when_upstream_missing(self):
        cfg = _cli_step_config(share_with_steps=["nonexistent_upstream"])
        task = {
            "task_id": "verify_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        resolve_execution_kind(self.db, self.plan, task)
        # A fresh workspace is reserved for verify_step.
        self.assertIsNotNone(task.get("workspace_id"))
        ws = find_workspace_by_task_id(self.db, self.plan.plan_id, "verify_step")
        self.assertIsNotNone(ws)

    def test_share_with_steps_skips_cleaned_upstream(self):
        # Reserve + clean upstream first.
        cfg_a = _cli_step_config()
        task_a = {
            "task_id": "code_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg_a,
        }
        resolve_execution_kind(self.db, self.plan, task_a)
        cleanup_workspace(self.db, task_a["workspace_id"])

        # Downstream step asking to share should NOT pick the cleaned one.
        cfg_b = _cli_step_config(share_with_steps=["code_step"])
        task_b = {
            "task_id": "verify_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg_b,
        }
        resolve_execution_kind(self.db, self.plan, task_b)
        self.assertNotEqual(task_b["workspace_id"], task_a["workspace_id"])

    def test_no_workspace_when_policy_is_none(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        task = {
            "task_id": "noop_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        resolve_execution_kind(self.db, self.plan, task)
        self.assertIsNone(task.get("workspace_id"))

    def test_workspace_lifecycle_transitions(self):
        cfg = _cli_step_config()
        task = {
            "task_id": "code_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        resolve_execution_kind(self.db, self.plan, task)
        ws_id = task["workspace_id"]
        # Simulate Tauri side writing back the path → active.
        update_workspace_path(self.db, ws_id, "/Users/me/.workspaces/code_step")
        ws = self.db.query(CoordinatorWorkspace).filter(
            CoordinatorWorkspace.workspace_id == ws_id
        ).first()
        self.assertEqual(ws.status, "active")
        self.assertEqual(ws.workspace_path, "/Users/me/.workspaces/code_step")
        # Promote.
        promote_workspace(self.db, ws_id)
        self.db.refresh(ws)
        self.assertEqual(ws.status, "promoted")


if __name__ == "__main__":
    unittest.main()
