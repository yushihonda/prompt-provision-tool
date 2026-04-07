"""Tests for external_cli artifact provenance helper.

The full integration path (finalize_execution → _record_coordinator_artifact)
requires a complete Execution / Workflow / Plan graph that is awkward
to set up in isolation. Instead we test the pure helper that does the
actual mapping; integration with finalize_execution is exercised
end-to-end against the live backend.
"""
from __future__ import annotations

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

from app.services.completion_service import (  # noqa: E402
    build_external_cli_provenance,
    build_http_provider_provenance,
)


class BuildExternalCliProvenanceTests(unittest.TestCase):
    def _full_meta(self) -> dict:
        return {
            "adapter_id": "claude-code-local",
            "adapter_name": "claude-code-local",
            "runtime": "claude_code",
            "status": "succeeded",
            "cwd": "/Users/me/project",
            "command": "claude",
            "command_line_preview": "claude -p \"hi\"",
            "exit_code": 0,
            "duration_ms": 1234,
            "stdout_truncated": False,
            "stderr_truncated": True,
            "changed_files": ["a.txt", "b.txt"],
            "capability_check_passed": True,
            "allow_writes": True,
            "allow_shell": False,
            "required_capabilities": ["file_read", "file_write", "workspace_aware"],
            "workspace_id": "ws-1",
            "workspace_mode": "temp_dir",
            "workspace_path": "/Users/me/project",
        }

    def test_full_round_trip(self):
        prov = build_external_cli_provenance(self._full_meta())
        # Strong-requirement keys.
        self.assertEqual(prov["execution_kind"], "external_cli")
        self.assertEqual(prov["adapter_type"], "external_cli")
        self.assertEqual(prov["adapter_name"], "claude-code-local")
        self.assertEqual(prov["runtime"], "claude_code")
        self.assertEqual(prov["cli_status"], "succeeded")
        self.assertEqual(prov["exit_code"], 0)
        self.assertEqual(prov["duration_ms"], 1234)
        self.assertEqual(prov["changed_files"], ["a.txt", "b.txt"])
        self.assertEqual(prov["changed_files_count"], 2)
        self.assertTrue(prov["capability_check_passed"])
        self.assertTrue(prov["allow_writes"])
        self.assertFalse(prov["allow_shell"])
        self.assertEqual(
            prov["required_capabilities"],
            ["file_read", "file_write", "workspace_aware"],
        )
        self.assertEqual(prov["workspace_id"], "ws-1")
        self.assertEqual(prov["workspace_mode"], "temp_dir")
        self.assertEqual(prov["workspace_path"], "/Users/me/project")
        self.assertEqual(prov["cwd"], "/Users/me/project")
        self.assertTrue(prov["stderr_truncated"])

    def test_codex_meta_runtime_only_difference(self):
        meta = self._full_meta()
        meta["adapter_id"] = "codex-local"
        meta["adapter_name"] = "codex-local"
        meta["runtime"] = "codex"
        meta["command"] = "codex"
        meta["command_line_preview"] = "codex -p \"...\""
        prov = build_external_cli_provenance(meta)
        self.assertEqual(prov["runtime"], "codex")
        self.assertEqual(prov["adapter_name"], "codex-local")
        self.assertEqual(prov["command"], "codex")
        # Schema is identical between Claude and Codex — only adapter/runtime differ.
        claude_prov = build_external_cli_provenance(self._full_meta())
        self.assertEqual(set(prov.keys()), set(claude_prov.keys()))

    def test_missing_changed_files_defaults_to_empty(self):
        meta = self._full_meta()
        del meta["changed_files"]
        prov = build_external_cli_provenance(meta)
        self.assertEqual(prov["changed_files"], [])
        self.assertEqual(prov["changed_files_count"], 0)

    def test_unified_base_keys_present_for_both_runtime_kinds(self):
        # Both runtime kinds must share these base keys.
        cli_meta = self._full_meta()
        cli_meta["selection_reason"] = "step_pref:external_cli:claude-code-local"
        cli_meta["approval_policy"] = "allow_write"
        cli_prov = build_external_cli_provenance(cli_meta)
        http_meta = {
            "selected_adapter_name": "local-llm-ollama",
            "actual_adapter_name": "remote-api-openai-compat",
            "selected_provider_mode": "local_preferred",
            "actual_provider_mode": "remote_only",
            "provider_selection_reason": "low_impact_local",
            "fallback_applied": True,
            "fallback_reason": "connect_error",
            "provider_attempt_count": 2,
            "preflight_status": "unreachable",
            "local_error_reason": "connect_error",
            "local_model_requested": "qwen2.5-coder:14b",
        }
        http_prov = build_http_provider_provenance(http_meta)
        # Unified base keys.
        for key in ("step_execution_kind", "adapter_id", "adapter_name", "runtime", "selection_reason"):
            self.assertIn(key, cli_prov)
            self.assertIn(key, http_prov)
        self.assertEqual(cli_prov["step_execution_kind"], "external_cli")
        self.assertEqual(http_prov["step_execution_kind"], "http_provider")
        self.assertEqual(cli_prov["selection_reason"], "step_pref:external_cli:claude-code-local")
        self.assertEqual(http_prov["selection_reason"], "low_impact_local")
        # http_prov retains its runtime-specific keys too.
        self.assertTrue(http_prov["fallback_applied"])
        self.assertEqual(http_prov["preflight_status"], "unreachable")

    def test_strong_requirement_questions_answerable_from_dict(self):
        prov = build_external_cli_provenance(self._full_meta())
        # Q1: which runtime executed the task?
        self.assertEqual(prov["runtime"], "claude_code")
        # Q3: did capability check pass?
        self.assertTrue(prov["capability_check_passed"])
        # Q4: where did it run?
        self.assertEqual(prov["cwd"], "/Users/me/project")
        # Q5: was file writing / shell allowed?
        self.assertTrue(prov["allow_writes"])
        self.assertFalse(prov["allow_shell"])
        # Q6: what changed?
        self.assertEqual(prov["changed_files"], ["a.txt", "b.txt"])
        # Was workspace isolation used?
        self.assertEqual(prov["workspace_id"], "ws-1")


if __name__ == "__main__":
    unittest.main()
