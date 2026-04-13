"""Tests for runtime-fallback bundle resolver and artifact metadata path."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.coordinator_service import (  # noqa: E402
    PROVIDER_LOCAL_ONLY,
    PROVIDER_LOCAL_PREFERRED,
    PROVIDER_REMOTE_ONLY,
    ROLE_JUDGE,
    ROLE_RESEARCHER,
    resolve_execution_provider_bundle,
)


def _plan(default_mode: str = PROVIDER_REMOTE_ONLY) -> SimpleNamespace:
    return SimpleNamespace(
        provider_policy=json.dumps(
            {"default_mode": default_mode, "escalation_rules": []}
        )
    )


def _local_adapter():
    return SimpleNamespace(
        adapter_id="aid-local",
        name="local-llm-ollama",
        transport="http",
        impl="http://localhost:11434/v1",
        provider_mode=PROVIDER_LOCAL_PREFERRED,
        supported_roles=json.dumps(["researcher", "writer"]),
        capabilities=json.dumps(["openai_compat"]),
        config=json.dumps({"default_model": "qwen2.5:14b"}),
    )


def _remote_adapter():
    return SimpleNamespace(
        adapter_id="aid-remote",
        name="remote-api-openai-compat",
        transport="http",
        impl="https://api.openai.com/v1",
        provider_mode=PROVIDER_REMOTE_ONLY,
        supported_roles=json.dumps(["researcher", "writer", "reviewer", "judge"]),
        capabilities=json.dumps([]),
        config=json.dumps({"default_model": "gpt-4o-mini"}),
    )


class BundleResolverTests(unittest.TestCase):
    def test_10_local_preferred_includes_fallback_payload(self):
        plan = _plan()
        task = {"role": ROLE_RESEARCHER, "impact_level": "low"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[_local_adapter(), _remote_adapter()],
        ):
            result = resolve_execution_provider_bundle(None, plan, task)
        self.assertEqual(result["provider_mode_selected"], PROVIDER_LOCAL_PREFERRED)
        self.assertIsNotNone(result["provider_payload"])
        self.assertIsNotNone(result["fallback_provider_payload"])
        self.assertEqual(result["selected_adapter_name"], "local-llm-ollama")
        self.assertEqual(result["fallback_adapter_name"], "remote-api-openai-compat")
        self.assertEqual(result["provider_payload"]["base_url"], "http://localhost:11434/v1")
        self.assertEqual(
            result["fallback_provider_payload"]["base_url"],
            "https://api.openai.com/v1",
        )

    def test_11_local_only_omits_fallback_payload(self):
        # local_only is enforced via plan policy default
        plan = _plan(default_mode=PROVIDER_LOCAL_ONLY)
        task = {"role": ROLE_RESEARCHER, "impact_level": "medium"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[_local_adapter(), _remote_adapter()],
        ):
            result = resolve_execution_provider_bundle(None, plan, task)
        # local_only is hit via policy_default; selected mode is local_only.
        self.assertEqual(result["provider_mode_selected"], PROVIDER_LOCAL_ONLY)
        self.assertIsNone(result["fallback_provider_payload"])

    def test_12_remote_only_omits_fallback_payload(self):
        plan = _plan()
        task = {"role": ROLE_RESEARCHER, "impact_level": "medium"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[_local_adapter(), _remote_adapter()],
        ):
            result = resolve_execution_provider_bundle(None, plan, task)
        self.assertEqual(result["provider_mode_selected"], PROVIDER_REMOTE_ONLY)
        self.assertIsNone(result["fallback_provider_payload"])

    def test_pre_routing_fallback_skips_runtime_fallback(self):
        plan = _plan()
        task = {"role": ROLE_RESEARCHER, "impact_level": "low"}
        # Only remote adapter exists -> pre-routing fallback fires.
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[_remote_adapter()],
        ):
            result = resolve_execution_provider_bundle(None, plan, task)
        self.assertEqual(result["provider_mode_selected"], PROVIDER_REMOTE_ONLY)
        self.assertTrue(result["pre_routing_fallback_occurred"])
        self.assertIsNone(result["fallback_provider_payload"])

    def test_judge_remote_only_no_fallback(self):
        plan = _plan()
        task = {"role": ROLE_JUDGE, "impact_level": "low"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[_local_adapter(), _remote_adapter()],
        ):
            result = resolve_execution_provider_bundle(None, plan, task)
        self.assertEqual(result["provider_mode_selected"], PROVIDER_REMOTE_ONLY)
        self.assertIsNone(result["fallback_provider_payload"])


class ArtifactProvenanceTests(unittest.TestCase):
    """Test that _record_coordinator_artifact prefers actual provider meta."""

    def _execution(self):
        return SimpleNamespace(
            id=42,
            agent_profile="explore",
            workflow_skill_id=7,
            workflow_execution_id=11,
            skill_order=2,
            retry_count=0,
        )

    def _patch_dependencies(self, plan_tasks=None):
        """Common patch context — record_artifact + plan lookup mocks."""
        plan = SimpleNamespace(
            plan_id="plan-1",
            tasks=json.dumps(plan_tasks or []),
        )
        return [
            patch(
                "app.services.completion_service.logger",
            ),
            patch(
                "app.services.coordinator_service.get_plan_by_workflow_execution",
                return_value=plan,
            ),
            patch(
                "app.services.coordinator_service.record_artifact",
                return_value=SimpleNamespace(artifact_id="art-1"),
            ),
            patch(
                "app.services.coordinator_service.record_event",
            ),
            patch(
                "app.services.coordinator_service.find_worker_for_task",
                return_value=None,
            ),
        ]

    def test_8_artifact_uses_actual_provider_meta_from_execution(self):
        from app.services import completion_service

        provider_meta = {
            "selected_provider_mode": "local_preferred",
            "selected_adapter_id": "aid-local",
            "selected_adapter_name": "local-llm-ollama",
            "selected_model": "qwen2.5:14b",
            "selected_base_url": "http://localhost:11434/v1",
            "provider_selection_reason": "low_impact_local",
            "actual_provider_mode": "remote_only",
            "actual_adapter_id": "aid-remote",
            "actual_adapter_name": "remote-api-openai-compat",
            "actual_model": "gpt-4o-mini",
            "actual_base_url": "https://api.openai.com/v1",
            "actual_transport": "http",
            "fallback_applied": True,
            "fallback_from_adapter_id": "aid-local",
            "fallback_to_adapter_id": "aid-remote",
            "fallback_reason": "connect_error",
            "provider_attempt_count": 2,
        }

        captured = {}
        with patch(
            "app.services.coordinator_service.get_plan_by_workflow_execution",
            return_value=SimpleNamespace(plan_id="plan-1", tasks="[]"),
        ), patch(
            "app.services.coordinator_service.record_artifact",
            side_effect=lambda *a, **k: (
                captured.update(k) or SimpleNamespace(artifact_id="art-1")
            ),
        ), patch(
            "app.services.coordinator_service.record_event",
        ), patch(
            "app.services.coordinator_service.find_worker_for_task",
            return_value=None,
        ):
            completion_service._record_coordinator_artifact(
                db=None,
                execution=self._execution(),
                output="result",
                model_used="gpt-4o-mini",
                provider_meta=provider_meta,
            )

        meta = captured["extra_metadata"]
        # Selected vs actual must round-trip exactly.
        self.assertEqual(meta["selected_adapter_id"], "aid-local")
        self.assertEqual(meta["actual_adapter_id"], "aid-remote")
        self.assertTrue(meta["fallback_applied"])
        self.assertEqual(meta["fallback_reason"], "connect_error")
        self.assertEqual(meta["provider_attempt_count"], 2)
        self.assertEqual(meta["actual_model"], "gpt-4o-mini")
        # Traceability fields populated.
        self.assertEqual(meta["task_id"], "task_7")
        self.assertEqual(meta["workflow_run_id"], 11)
        self.assertNotIn("legacy_metadata_path", meta)

    def test_9_legacy_path_when_provider_meta_missing(self):
        from app.services import completion_service

        captured = {}
        plan_tasks = [{"workflow_skill_id": 7, "role": ROLE_RESEARCHER, "impact_level": "low"}]
        with patch(
            "app.services.coordinator_service.get_plan_by_workflow_execution",
            return_value=SimpleNamespace(
                plan_id="plan-1", tasks=json.dumps(plan_tasks),
                provider_policy=json.dumps({"default_mode": PROVIDER_REMOTE_ONLY, "escalation_rules": []}),
            ),
        ), patch(
            "app.services.coordinator_service.record_artifact",
            side_effect=lambda *a, **k: (
                captured.update(k) or SimpleNamespace(artifact_id="art-1")
            ),
        ), patch(
            "app.services.coordinator_service.record_event",
        ), patch(
            "app.services.coordinator_service.find_worker_for_task",
            return_value=None,
        ), patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[_local_adapter(), _remote_adapter()],
        ):
            completion_service._record_coordinator_artifact(
                db=None,
                execution=self._execution(),
                output="result",
                model_used="qwen2.5:14b",
                provider_meta=None,
            )

        meta = captured["extra_metadata"]
        # legacy path emits selected_* but no actual_*.
        self.assertTrue(meta.get("legacy_metadata_path"))
        self.assertEqual(meta.get("selected_adapter_name"), "local-llm-ollama")
        self.assertNotIn("actual_adapter_id", meta)


if __name__ == "__main__":
    unittest.main()
