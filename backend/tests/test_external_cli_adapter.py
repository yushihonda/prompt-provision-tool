"""Tests for external CLI adapter (Claude Code) registration and payload."""
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

from app.models import Base, CoordinatorAdapter  # noqa: E402
from app.services.coordinator_extensions import seed_default_adapters  # noqa: E402
from app.services.external_cli_adapters import (  # noqa: E402
    ADAPTER_NAME_CLAUDE_CODE,
    DEFAULT_CLAUDE_TIMEOUT_MS,
    build_external_cli_payload,
    is_external_cli_payload,
)

SessionLocal = _database.SessionLocal


class ExternalCliAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=_test_engine)

    def setUp(self):
        self.db = SessionLocal()
        self.db.query(CoordinatorAdapter).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_seed_includes_claude_code_local(self):
        seed_default_adapters(self.db)
        row = (
            self.db.query(CoordinatorAdapter)
            .filter(CoordinatorAdapter.name == ADAPTER_NAME_CLAUDE_CODE)
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.adapter_type, "external_cli")
        self.assertEqual(row.transport, "external_cli")
        self.assertEqual(row.runtime, "claude_code")
        self.assertEqual(row.impl, "claude")
        config = json.loads(row.config)
        self.assertEqual(config["runtime"], "claude_code")
        self.assertEqual(config["command"], "claude")
        self.assertTrue(config["requires_local_auth"])

    def test_build_payload_happy_path(self):
        seed_default_adapters(self.db)
        adapter = (
            self.db.query(CoordinatorAdapter)
            .filter(CoordinatorAdapter.name == ADAPTER_NAME_CLAUDE_CODE)
            .first()
        )
        payload = build_external_cli_payload(
            adapter,
            cwd="/Users/me/project",
            prompt="do the thing",
            task_id="task-1",
            workflow_run_id="run-1",
            allow_writes=True,
            allow_shell=False,
        )
        self.assertEqual(payload["transport"], "external_cli")
        self.assertEqual(payload["adapter_name"], "claude-code-local")
        self.assertEqual(payload["runtime"], "claude_code")
        self.assertEqual(payload["command"], "claude")
        self.assertEqual(payload["cwd"], "/Users/me/project")
        self.assertEqual(payload["prompt"], "do the thing")
        self.assertEqual(payload["task_id"], "task-1")
        self.assertEqual(payload["workflow_run_id"], "run-1")
        self.assertTrue(payload["allow_writes"])
        self.assertFalse(payload["allow_shell"])
        self.assertEqual(payload["timeout_ms"], DEFAULT_CLAUDE_TIMEOUT_MS)
        self.assertTrue(payload["requires_local_auth"])

    def test_build_payload_returns_none_for_http_adapter(self):
        from app.services.coordinator_extensions import register_adapter
        adapter = register_adapter(
            self.db,
            name="local-llm-ollama",
            adapter_type="local_llm",
            provider_mode="local_preferred",
            transport="http",
            impl="http://localhost:11434/v1",
        )
        payload = build_external_cli_payload(
            adapter,
            cwd="/x",
            prompt="hi",
            task_id="t",
            workflow_run_id="r",
        )
        self.assertIsNone(payload)

    def test_build_payload_returns_none_for_none_adapter(self):
        self.assertIsNone(
            build_external_cli_payload(
                None, cwd="/x", prompt="hi", task_id="t", workflow_run_id="r"
            )
        )

    def test_is_external_cli_payload(self):
        self.assertTrue(is_external_cli_payload({"transport": "external_cli"}))
        self.assertFalse(is_external_cli_payload({"transport": "http"}))
        self.assertFalse(is_external_cli_payload(None))
        self.assertFalse(is_external_cli_payload({}))

    def test_build_payload_timeout_override(self):
        seed_default_adapters(self.db)
        adapter = (
            self.db.query(CoordinatorAdapter)
            .filter(CoordinatorAdapter.name == ADAPTER_NAME_CLAUDE_CODE)
            .first()
        )
        payload = build_external_cli_payload(
            adapter, cwd="/x", prompt="hi",
            task_id="t", workflow_run_id="r",
            timeout_ms=5000,
        )
        self.assertEqual(payload["timeout_ms"], 5000)


if __name__ == "__main__":
    unittest.main()
