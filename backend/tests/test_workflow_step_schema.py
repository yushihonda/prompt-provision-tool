"""Tests for workflow_step_schema."""
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

from app.services.workflow_step_schema import (  # noqa: E402
    StepApprovalMeta,
    StepExecutionConfig,
    StepExecutionMeta,
    StepWorkspaceMeta,
    default_step_execution_config,
    is_legacy_step,
    merge_execution_config_into_config_json,
    parse_execution_config,
)


class WorkflowStepSchemaTests(unittest.TestCase):
    def test_legacy_empty_config_returns_default(self):
        cfg = parse_execution_config(None)
        self.assertEqual(cfg.execution.execution_kind, "auto")
        self.assertEqual(cfg.workspace.workspace_policy, "none")
        self.assertEqual(cfg.approval.policy, "read_only")
        self.assertTrue(is_legacy_step(cfg))

    def test_legacy_config_without_execution_config_key(self):
        raw = json.dumps({"foo": "bar", "input_mapping": "..."})
        cfg = parse_execution_config(raw)
        self.assertTrue(is_legacy_step(cfg))

    def test_full_round_trip(self):
        original = StepExecutionConfig(
            execution=StepExecutionMeta(
                execution_kind="external_cli",
                preferred_adapter="claude-code-local",
                candidate_adapters=["codex-local"],
                required_capabilities=["file_read", "file_write", "shell_exec"],
                cli_runtime_hint="claude_code",
                cwd_hint="/Users/me/project",
            ),
            workspace=StepWorkspaceMeta(
                workspace_policy="temp_dir",
                share_with_steps=["step_42"],
                promote_on="accepted",
                cleanup_on="failed",
            ),
            approval=StepApprovalMeta(
                policy="allow_write",
                allow_writes=True,
                allow_shell=False,
            ),
        )
        merged = merge_execution_config_into_config_json({"existing": "value"}, original)
        loaded_dict = json.loads(merged)
        self.assertEqual(loaded_dict["existing"], "value")
        round_trip = parse_execution_config(merged)
        self.assertEqual(round_trip.execution.execution_kind, "external_cli")
        self.assertEqual(round_trip.execution.preferred_adapter, "claude-code-local")
        self.assertEqual(round_trip.execution.candidate_adapters, ["codex-local"])
        self.assertEqual(
            round_trip.execution.required_capabilities,
            ["file_read", "file_write", "shell_exec"],
        )
        self.assertEqual(round_trip.workspace.workspace_policy, "temp_dir")
        self.assertEqual(round_trip.workspace.share_with_steps, ["step_42"])
        self.assertEqual(round_trip.approval.policy, "allow_write")
        self.assertTrue(round_trip.approval.allow_writes)
        self.assertFalse(round_trip.approval.allow_shell)

    def test_malformed_json_falls_back_to_default(self):
        cfg = parse_execution_config("{not valid json")
        self.assertTrue(is_legacy_step(cfg))

    def test_unknown_top_level_keys_preserved_on_round_trip(self):
        raw_dict = {
            "foo": "bar",
            "execution_config": {
                "execution": {"execution_kind": "auto"},
            },
        }
        raw = json.dumps(raw_dict)
        cfg = parse_execution_config(raw)
        merged = merge_execution_config_into_config_json(raw, cfg)
        loaded = json.loads(merged)
        self.assertEqual(loaded["foo"], "bar")
        self.assertIn("execution_config", loaded)

    def test_invalid_enum_value_falls_back(self):
        raw = json.dumps({
            "execution_config": {
                "execution": {"execution_kind": "magic_unicorn"},
            }
        })
        cfg = parse_execution_config(raw)
        # Falls back to default — execution_kind is auto, not magic_unicorn.
        self.assertEqual(cfg.execution.execution_kind, "auto")

    def test_default_helper_matches_parser_output(self):
        from_helper = default_step_execution_config()
        from_parser = parse_execution_config(None)
        self.assertEqual(from_helper.model_dump(), from_parser.model_dump())

    def test_admin_form_round_trip_shape(self):
        """The admin form sends the same shape that the parser
        produces. Lock the contract."""
        from_form = {
            "schema_version": "1.0",
            "execution": {
                "execution_kind": "external_cli",
                "preferred_adapter": "claude-code-local",
                "candidate_adapters": [],
                "required_capabilities": ["file_read", "file_write"],
                "cli_runtime_hint": None,
                "cwd_hint": "/Users/me/project",
            },
            "workspace": {
                "workspace_policy": "temp_dir",
                "share_with_steps": [],
                "promote_on": "accepted",
                "cleanup_on": "failed",
            },
            "approval": {
                "policy": "allow_write",
                "allow_writes": True,
                "allow_shell": False,
            },
            "artifact_contract": {
                "expected_type": None,
                "must_include_files": False,
                "must_include_diff": False,
            },
        }
        # Wrap as the admin endpoint stores it.
        config_json = json.dumps({"existing": "kept", "execution_config": from_form})
        cfg = parse_execution_config(config_json)
        self.assertEqual(cfg.execution.execution_kind, "external_cli")
        self.assertEqual(cfg.execution.preferred_adapter, "claude-code-local")
        self.assertEqual(cfg.workspace.workspace_policy, "temp_dir")
        self.assertTrue(cfg.approval.allow_writes)
        self.assertFalse(is_legacy_step(cfg))
        # Round-trip preserves the unrelated key.
        merged = merge_execution_config_into_config_json(config_json, cfg)
        loaded = json.loads(merged)
        self.assertEqual(loaded["existing"], "kept")
        self.assertEqual(loaded["execution_config"]["execution"]["preferred_adapter"], "claude-code-local")

    def test_partial_execution_block(self):
        raw = json.dumps({
            "execution_config": {
                "execution": {
                    "execution_kind": "external_cli",
                    "preferred_adapter": "codex-local",
                }
            }
        })
        cfg = parse_execution_config(raw)
        self.assertEqual(cfg.execution.execution_kind, "external_cli")
        self.assertEqual(cfg.execution.preferred_adapter, "codex-local")
        # Other blocks default.
        self.assertEqual(cfg.workspace.workspace_policy, "none")
        self.assertEqual(cfg.approval.policy, "read_only")
        self.assertFalse(is_legacy_step(cfg))


if __name__ == "__main__":
    unittest.main()
