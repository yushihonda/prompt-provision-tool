"""Approval policy enforcement at planner time."""
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
from app.services.coordinator_extensions import register_adapter, seed_default_adapters  # noqa: E402
from app.services.coordinator_service import (  # noqa: E402
    EXECUTION_KIND_EXTERNAL_CLI,
    EXECUTION_KIND_HTTP_PROVIDER,
    PROVIDER_REMOTE_ONLY,
    ROLE_WRITER,
    resolve_execution_kind,
)
from app.services.workflow_step_schema import (  # noqa: E402
    StepApprovalMeta,
    StepExecutionConfig,
    StepExecutionMeta,
)

SessionLocal = _database.SessionLocal


def _make_plan(db) -> CoordinatorPlan:
    plan = CoordinatorPlan(
        plan_id="plan-approval",
        workflow_execution_id=1,
        goal="t",
        tasks=json.dumps([]),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


class ApprovalPolicyEnforcementTests(unittest.TestCase):
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

    def test_read_only_step_routes_to_claude_without_write_caps(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="read_only"),
        )
        task = {
            "task_id": "review_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        payload = result["external_cli_payload"]
        self.assertFalse(payload["allow_writes"])
        self.assertFalse(payload["allow_shell"])

    def test_allow_write_step_passes_through_flags(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        task = {
            "task_id": "code_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        payload = result["external_cli_payload"]
        self.assertTrue(payload["allow_writes"])

    def test_capability_mismatch_falls_back_to_http(self):
        # Register a synthetic external_cli adapter with NO file_write capability.
        register_adapter(
            self.db,
            name="restricted-cli",
            adapter_type="external_cli",
            provider_mode=PROVIDER_REMOTE_ONLY,
            transport="external_cli",
            runtime="restricted",
            impl="restricted",
            capabilities=["file_read"],  # explicitly NO file_write / shell_exec
            config={"runtime": "restricted", "command": "/bin/true"},
        )
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="restricted-cli",
                cli_runtime_hint="restricted",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        task = {
            "task_id": "blocked_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertIn("step_capability_mismatch:restricted-cli", result["selection_reason"])
        self.assertIn("file_write", result["selection_reason"])

    def test_shell_exec_required_but_adapter_lacks_it(self):
        register_adapter(
            self.db,
            name="no-shell-cli",
            adapter_type="external_cli",
            provider_mode=PROVIDER_REMOTE_ONLY,
            transport="external_cli",
            runtime="no_shell",
            impl="no_shell",
            capabilities=["file_read", "file_write"],  # no shell_exec
            config={"runtime": "no_shell", "command": "/bin/true"},
        )
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="no-shell-cli",
                cli_runtime_hint="no_shell",
            ),
            approval=StepApprovalMeta(
                policy="allow_shell",
                allow_shell=True,
            ),
        )
        task = {
            "task_id": "shell_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertIn("shell_exec", result["selection_reason"])

    def test_ask_before_shell_does_not_grant_shell(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="ask_before_shell"),
        )
        task = {
            "task_id": "ask_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        payload = result["external_cli_payload"]
        # ask_before_shell currently behaves like read_only; the
        # interactive confirmation modal is a planned follow-up.
        self.assertFalse(payload["allow_shell"])


if __name__ == "__main__":
    unittest.main()
