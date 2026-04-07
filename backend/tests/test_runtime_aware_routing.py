"""Tests for Phase 4.2 — resolve_execution_kind reads StepExecutionConfig."""
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

from app.models import Base, CoordinatorAdapter, CoordinatorPlan  # noqa: E402
from app.services.coordinator_extensions import seed_default_adapters  # noqa: E402
from app.services.coordinator_service import (  # noqa: E402
    EXECUTION_KIND_EXTERNAL_CLI,
    EXECUTION_KIND_HTTP_PROVIDER,
    ROLE_JUDGE,
    ROLE_WRITER,
    resolve_execution_kind,
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


class RuntimeAwareRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=_test_engine)

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(CoordinatorAdapter).delete()
        self.db.query(CoordinatorPlan).delete()
        self.db.commit()
        seed_default_adapters(self.db)
        self.plan = _make_plan(self.db)

    def tearDown(self):
        self.db.close()

    def test_step_pref_external_cli_claude(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        task = {
            "task_id": "t1",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "prompt": "do the thing",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(result["adapter_name"], "claude-code-local")
        self.assertEqual(result["runtime"], "claude_code")
        self.assertEqual(result["selection_reason"], "step_pref:external_cli:claude-code-local")

    def test_step_candidate_codex_when_preferred_missing(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="nonexistent-cli",
                candidate_adapters=["codex-local"],
                cli_runtime_hint="codex",
            ),
            approval=StepApprovalMeta(policy="read_only"),
        )
        task = {
            "task_id": "t2",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "prompt": "review",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(result["adapter_name"], "codex-local")
        self.assertTrue(result["selection_reason"].startswith("step_candidate:external_cli:"))

    def test_step_pref_external_cli_falls_through_when_no_cwd(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
        )
        task = {
            "task_id": "t3",
            "role": ROLE_WRITER,
            "_step_execution_config": cfg,
            # no cwd_hint, no workspace_path
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)

    def test_judge_with_full_external_cli_config_still_remote(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        task = {
            "task_id": "t4",
            "role": ROLE_JUDGE,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertEqual(result["selection_reason"], "judge_forced_remote")

    def test_legacy_step_unchanged_behavior(self):
        # No _step_execution_config attached → routes via existing http path.
        task = {
            "task_id": "t5",
            "role": ROLE_WRITER,
            "writes_files": False,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertIsNone(result["external_cli_payload"])

    def test_explicit_legacy_default_config_unchanged_behavior(self):
        cfg = StepExecutionConfig()  # all defaults
        task = {
            "task_id": "t6",
            "role": ROLE_WRITER,
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)

    def test_provider_kind_skips_external_cli_branch(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="provider",
                preferred_adapter="claude-code-local",  # ignored
            ),
        )
        task = {
            "task_id": "t7",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)

    def test_workspace_meta_propagates(self):
        cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            workspace=StepWorkspaceMeta(
                workspace_policy="temp_dir",
                share_with_steps=["step_99"],
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        task = {
            "task_id": "t8",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": cfg,
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(task.get("_workspace_policy"), "temp_dir")
        self.assertEqual(task.get("_workspace_share_with_steps"), ["step_99"])


if __name__ == "__main__":
    unittest.main()
