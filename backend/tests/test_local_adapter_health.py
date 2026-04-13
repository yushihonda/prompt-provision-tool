"""Tests for refresh_local_adapter_health and update_adapter_health detail blob."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Set required env vars BEFORE importing app modules so pydantic Settings
# does not abort on missing DB credentials. Tests use an in-memory sqlite
# DB so the real connection string is irrelevant.
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used")
os.environ.setdefault("ENCRYPTION_KEY", "0" * 32)

# Allow `from app...` imports.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Override the engine to use in-memory sqlite before importing modules
# that bind to it.
import sqlalchemy  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as _database  # noqa: E402

_test_engine = sqlalchemy.create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}
)
_database.engine = _test_engine
_database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

from app.models import Base, CoordinatorAdapter  # noqa: E402
from app.services.coordinator_extensions import (  # noqa: E402
    refresh_local_adapter_health,
    register_adapter,
    update_adapter_health,
)

SessionLocal = _database.SessionLocal
engine = _test_engine


class LocalAdapterHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        # Clear adapters between tests.
        self.db.query(CoordinatorAdapter).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _seed_local_adapter(self) -> CoordinatorAdapter:
        return register_adapter(
            self.db,
            name="local-llm-ollama",
            adapter_type="local_llm",
            provider_mode="local_preferred",
            transport="http",
            runtime="http",
            impl="http://localhost:11434/v1",
            config={"endpoint": "http://localhost:11434/v1"},
        )

    def test_refresh_writes_healthy(self):
        adapter = self._seed_local_adapter()

        def fake_probe(base_url):
            return {
                "reachable": True,
                "models": ["qwen2.5-coder:14b", "llama3:8b"],
                "latency_ms": 12,
                "error": None,
            }

        updated = refresh_local_adapter_health(
            self.db, adapter.adapter_id, probe_fn=fake_probe
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.health_status, "healthy")
        config = json.loads(updated.config)
        self.assertIn("last_health_detail", config)
        self.assertEqual(
            config["last_health_detail"]["models"],
            ["qwen2.5-coder:14b", "llama3:8b"],
        )
        self.assertEqual(config["last_health_detail"]["status"], "healthy")

    def test_refresh_writes_unreachable(self):
        adapter = self._seed_local_adapter()

        def fake_probe(base_url):
            return {
                "reachable": False,
                "models": [],
                "latency_ms": None,
                "error": "connect_error: refused",
            }

        updated = refresh_local_adapter_health(
            self.db, adapter.adapter_id, probe_fn=fake_probe
        )
        self.assertEqual(updated.health_status, "unreachable")
        config = json.loads(updated.config)
        self.assertEqual(
            config["last_health_detail"]["error"],
            "connect_error: refused",
        )

    def test_refresh_writes_degraded_on_empty_models(self):
        adapter = self._seed_local_adapter()

        def fake_probe(base_url):
            return {
                "reachable": True,
                "models": [],
                "latency_ms": 5,
                "error": None,
            }

        updated = refresh_local_adapter_health(
            self.db, adapter.adapter_id, probe_fn=fake_probe
        )
        self.assertEqual(updated.health_status, "degraded")

    def test_refresh_unknown_adapter_returns_none(self):
        result = refresh_local_adapter_health(
            self.db, "nonexistent-id", probe_fn=lambda b: {"reachable": True, "models": ["a"]}
        )
        self.assertIsNone(result)

    def test_refresh_skips_non_http_adapter(self):
        adapter = register_adapter(
            self.db,
            name="internal-sidecar",
            adapter_type="internal",
            provider_mode="remote_only",
            transport="process_stdio",
        )
        original_health = adapter.health_status
        result = refresh_local_adapter_health(
            self.db, adapter.adapter_id, probe_fn=lambda b: {"reachable": False}
        )
        self.assertIsNotNone(result)
        # Health unchanged because we early-return for non-http transports.
        self.assertEqual(result.health_status, original_health)

    def test_update_adapter_health_with_detail_merges_config(self):
        adapter = self._seed_local_adapter()
        updated = update_adapter_health(
            self.db,
            adapter.adapter_id,
            "healthy",
            detail={"models": ["a"], "latency_ms": 1, "error": None},
        )
        config = json.loads(updated.config)
        # original config keys preserved
        self.assertEqual(config.get("endpoint"), "http://localhost:11434/v1")
        # new detail attached
        self.assertIn("last_health_detail", config)


if __name__ == "__main__":
    unittest.main()
