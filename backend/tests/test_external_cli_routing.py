"""Tests for resolve_execution_kind (Phase 3.4)."""
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


class ExternalCliRoutingTests(unittest.TestCase):
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

    def test_judge_never_routes_to_external_cli_even_when_opted_in(self):
        task = {
            "task_id": "t1",
            "role": ROLE_JUDGE,
            "prefer_external_cli": True,
            "cli_runtime_hint": "claude_code",
            "writes_files": True,
            "cwd_hint": "/Users/me/project",
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertEqual(result["selection_reason"], "judge_forced_remote")
        self.assertIsNone(result["external_cli_payload"])

    def test_writer_with_prefer_cli_routes_to_claude(self):
        task = {
            "task_id": "t2",
            "role": ROLE_WRITER,
            "prefer_external_cli": True,
            "cli_runtime_hint": "claude_code",
            "writes_files": True,
            "allow_shell": False,
            "cwd_hint": "/Users/me/project",
            "prompt": "do the thing",
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(result["runtime"], "claude_code")
        self.assertEqual(result["adapter_name"], "claude-code-local")
        payload = result["external_cli_payload"]
        self.assertIsNotNone(payload)
        self.assertEqual(payload["transport"], "external_cli")
        self.assertEqual(payload["runtime"], "claude_code")
        self.assertEqual(payload["cwd"], "/Users/me/project")
        self.assertEqual(payload["prompt"], "do the thing")
        self.assertTrue(payload["allow_writes"])
        self.assertFalse(payload["allow_shell"])
        self.assertIn("file_read", payload["required_capabilities"])
        self.assertIn("file_write", payload["required_capabilities"])

    def test_writer_with_prefer_cli_routes_to_codex(self):
        task = {
            "task_id": "t3",
            "role": ROLE_WRITER,
            "prefer_external_cli": True,
            "cli_runtime_hint": "codex",
            "writes_files": True,
            "cwd_hint": "/Users/me/project",
            "prompt": "do the thing",
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_EXTERNAL_CLI)
        self.assertEqual(result["runtime"], "codex")
        self.assertEqual(result["adapter_name"], "codex-local")

    def test_writer_with_prefer_cli_but_no_cwd_falls_through_to_http(self):
        task = {
            "task_id": "t4",
            "role": ROLE_WRITER,
            "prefer_external_cli": True,
            "cli_runtime_hint": "claude_code",
            "writes_files": True,
            # no cwd_hint, no workspace_path
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertIsNone(result["external_cli_payload"])

    def test_writer_without_prefer_cli_routes_to_http(self):
        task = {
            "task_id": "t5",
            "role": ROLE_WRITER,
            "writes_files": False,
            "cwd_hint": "/Users/me/project",
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)
        self.assertIsNone(result["external_cli_payload"])

    def test_unknown_runtime_hint_falls_through_to_http(self):
        task = {
            "task_id": "t6",
            "role": ROLE_WRITER,
            "prefer_external_cli": True,
            "cli_runtime_hint": "nonexistent_runtime",
            "writes_files": False,
            "cwd_hint": "/Users/me/project",
        }
        result = resolve_execution_kind(self.db, self.plan, task)
        self.assertEqual(result["execution_kind"], EXECUTION_KIND_HTTP_PROVIDER)


if __name__ == "__main__":
    unittest.main()
