"""End-to-end mixed-runtime workflow routing.

Validates that a single workflow can have 4 steps that each route to
a different execution runtime:

    step 1 (researcher, provider)    -> http_provider (remote/local)
    step 2 (writer, ollama hint)     -> http_provider (local_preferred)
    step 3 (writer, claude_code CLI) -> external_cli (claude-code-local)
    step 4 (reviewer, codex CLI)     -> external_cli (codex-local)
    step 5 (judge)                   -> http_provider (hard rule)

Each step carries its own StepExecutionConfig via _step_execution_config
in the task dict. Asserts that:
  - every step resolves to the correct runtime
  - shared workspace flows from code step to verify step
  - judge is never routed to external_cli even with opt-in config
  - artifact provenance will be runtime-agnostic (bundle shape
    matches the same contract for both runtime kinds)
"""
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
    EXECUTION_KIND_HTTP_PROVIDER,
    ROLE_JUDGE,
    ROLE_RESEARCHER,
    ROLE_REVIEWER,
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


def _make_plan(db) -> CoordinatorPlan:
    plan = CoordinatorPlan(
        plan_id="plan-mixed-e2e",
        workflow_execution_id=777,
        goal="mixed runtime e2e",
        tasks=json.dumps([]),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


class MixedRuntimeE2ETests(unittest.TestCase):
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

    def test_four_step_mixed_workflow_routes_correctly(self):
        # Step 1: search via provider (default HTTP routing)
        search_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="provider",
            ),
        )
        search_task = {
            "task_id": "search_step",
            "role": ROLE_RESEARCHER,
            "_step_execution_config": search_cfg,
        }
        search_result = resolve_execution_kind(self.db, self.plan, search_task)
        self.assertEqual(search_result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)

        # Step 2: plan via Ollama (local HTTP)
        plan_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="provider",
            ),
        )
        plan_task = {
            "task_id": "plan_step",
            "role": ROLE_WRITER,
            "impact_level": "low",  # triggers existing local_preferred routing
            "_step_execution_config": plan_cfg,
        }
        plan_result = resolve_execution_kind(self.db, self.plan, plan_task)
        self.assertEqual(plan_result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)

        # Step 3: code via Claude Code CLI
        code_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            workspace=StepWorkspaceMeta(workspace_policy="temp_dir"),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        code_task = {
            "task_id": "code_step",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": code_cfg,
        }
        code_result = resolve_execution_kind(self.db, self.plan, code_task)
        self.assertEqual(code_result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(code_result["adapter_name"], "claude-code-local")
        self.assertEqual(code_result["runtime"], "claude_code")
        code_payload = code_result["external_cli_payload"]
        self.assertTrue(code_payload["allow_writes"])
        self.assertIsNotNone(code_payload["workspace_id"])
        self.assertEqual(code_payload["workspace_mode"], "temp_dir")

        # Step 4: verify via Codex CLI, sharing code_step's workspace, read-only
        verify_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="codex-local",
                cli_runtime_hint="codex",
            ),
            workspace=StepWorkspaceMeta(
                workspace_policy="temp_dir",
                share_with_steps=["code_step"],
            ),
            approval=StepApprovalMeta(policy="read_only"),
        )
        verify_task = {
            "task_id": "verify_step",
            "role": ROLE_REVIEWER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": verify_cfg,
        }
        verify_result = resolve_execution_kind(self.db, self.plan, verify_task)
        self.assertEqual(verify_result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(verify_result["adapter_name"], "codex-local")
        self.assertEqual(verify_result["runtime"], "codex")
        verify_payload = verify_result["external_cli_payload"]
        # Must share workspace with code_step.
        self.assertEqual(verify_payload["workspace_id"], code_payload["workspace_id"])
        self.assertFalse(verify_payload["allow_writes"])
        self.assertFalse(verify_payload["allow_shell"])

        # Step 5: judge — hard rule says remote HTTP even with full CLI opt-in
        judge_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        judge_task = {
            "task_id": "judge_step",
            "role": ROLE_JUDGE,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": judge_cfg,
        }
        judge_result = resolve_execution_kind(self.db, self.plan, judge_task)
        self.assertEqual(judge_result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertEqual(judge_result["selection_reason"], "judge_forced_remote")
        self.assertIsNone(judge_result["external_cli_payload"])

    def test_contract_base_keys_shared_across_runtimes(self):
        """Both external_cli runtimes emit the same payload contract."""
        base_keys = {
            "transport",
            "adapter_id",
            "adapter_name",
            "runtime",
            "command",
            "cwd",
            "prompt",
            "task_id",
            "workflow_run_id",
            "allow_writes",
            "allow_shell",
            "timeout_ms",
            "required_capabilities",
            "approval_policy",
        }

        claude_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                cli_runtime_hint="claude_code",
            ),
            approval=StepApprovalMeta(policy="allow_write", allow_writes=True),
        )
        claude_task = {
            "task_id": "c",
            "role": ROLE_WRITER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": claude_cfg,
        }
        claude_payload = resolve_execution_kind(
            self.db, self.plan, claude_task
        )["external_cli_payload"]

        codex_cfg = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="codex-local",
                cli_runtime_hint="codex",
            ),
            approval=StepApprovalMeta(policy="read_only"),
        )
        codex_task = {
            "task_id": "x",
            "role": ROLE_REVIEWER,
            "cwd_hint": "/Users/me/project",
            "_step_execution_config": codex_cfg,
        }
        codex_payload = resolve_execution_kind(
            self.db, self.plan, codex_task
        )["external_cli_payload"]

        for k in base_keys:
            self.assertIn(k, claude_payload, f"claude payload missing {k}")
            self.assertIn(k, codex_payload, f"codex payload missing {k}")
        self.assertNotEqual(claude_payload["runtime"], codex_payload["runtime"])
        self.assertNotEqual(claude_payload["adapter_name"], codex_payload["adapter_name"])


if __name__ == "__main__":
    unittest.main()
