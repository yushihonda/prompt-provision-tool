"""Tests for provider routing hard rules and adapter resolution."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.coordinator_service import (  # noqa: E402
    PROVIDER_LOCAL_PREFERRED,
    PROVIDER_REMOTE_ONLY,
    ROLE_JUDGE,
    ROLE_RESEARCHER,
    ROLE_WRITER,
    resolve_execution_provider,
    route_provider_mode_with_reason,
)
from app.services.coordinator_extensions import build_provider_payload  # noqa: E402


def _plan(default_mode: str = PROVIDER_REMOTE_ONLY) -> SimpleNamespace:
    return SimpleNamespace(
        provider_policy=json.dumps(
            {"default_mode": default_mode, "escalation_rules": []}
        )
    )


class HardRuleTests(unittest.TestCase):
    def test_a_low_impact_researcher_goes_local(self):
        mode, reason = route_provider_mode_with_reason(
            _plan(),
            role=ROLE_RESEARCHER,
            impact_level="low",
        )
        self.assertEqual(mode, PROVIDER_LOCAL_PREFERRED)
        self.assertEqual(reason, "low_impact_local")

    def test_b_judge_always_remote(self):
        mode, reason = route_provider_mode_with_reason(
            _plan(),
            role=ROLE_JUDGE,
            impact_level="low",
        )
        self.assertEqual(mode, PROVIDER_REMOTE_ONLY)
        self.assertEqual(reason, "judge_forced_remote")

    def test_c_writes_files_always_remote(self):
        mode, reason = route_provider_mode_with_reason(
            _plan(),
            role=ROLE_WRITER,
            impact_level="low",
            writes_files=True,
        )
        self.assertEqual(mode, PROVIDER_REMOTE_ONLY)
        self.assertEqual(reason, "writes_files_forced_remote")

    def test_d_retry_escalates_to_remote(self):
        mode, reason = route_provider_mode_with_reason(
            _plan(),
            role=ROLE_RESEARCHER,
            impact_level="low",
            retry_count=2,
        )
        self.assertEqual(mode, PROVIDER_REMOTE_ONLY)
        self.assertEqual(reason, "retry_escalation")

    def test_e_high_impact_remote(self):
        mode, reason = route_provider_mode_with_reason(
            _plan(),
            role=ROLE_RESEARCHER,
            impact_level="high",
        )
        self.assertEqual(mode, PROVIDER_REMOTE_ONLY)
        self.assertEqual(reason, "high_impact_remote")

    def test_policy_default_when_no_match(self):
        mode, reason = route_provider_mode_with_reason(
            _plan(),
            role=ROLE_WRITER,
            impact_level="medium",
        )
        self.assertEqual(mode, PROVIDER_REMOTE_ONLY)
        self.assertEqual(reason, "policy_default")


class BuildProviderPayloadTests(unittest.TestCase):
    def test_http_adapter_produces_payload(self):
        adapter = SimpleNamespace(
            adapter_id="aid-1",
            name="local-llm-ollama",
            transport="http",
            impl="http://localhost:11434/v1",
            provider_mode=PROVIDER_LOCAL_PREFERRED,
            config=json.dumps({"default_model": "qwen2.5:14b"}),
        )
        payload = build_provider_payload(adapter)
        self.assertEqual(payload["transport"], "http")
        self.assertEqual(payload["base_url"], "http://localhost:11434/v1")
        self.assertEqual(payload["model"], "qwen2.5:14b")
        self.assertEqual(payload["adapter_name"], "local-llm-ollama")
        self.assertEqual(payload["provider_mode"], PROVIDER_LOCAL_PREFERRED)

    def test_non_http_adapter_returns_none(self):
        adapter = SimpleNamespace(
            adapter_id="aid-2",
            name="internal-sidecar",
            transport="process_stdio",
            impl="sidecar.main",
            provider_mode=PROVIDER_REMOTE_ONLY,
            config=None,
        )
        self.assertIsNone(build_provider_payload(adapter))

    def test_none_adapter_returns_none(self):
        self.assertIsNone(build_provider_payload(None))

    def test_explicit_model_overrides_default(self):
        adapter = SimpleNamespace(
            adapter_id="aid-3",
            name="local-llm-ollama",
            transport="http",
            impl="http://localhost:11434/v1",
            provider_mode=PROVIDER_LOCAL_PREFERRED,
            config=json.dumps({"default_model": "qwen2.5:14b"}),
        )
        payload = build_provider_payload(adapter, model="llama3:8b")
        self.assertEqual(payload["model"], "llama3:8b")


class ResolveExecutionProviderTests(unittest.TestCase):
    def _local_adapter(self):
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

    def _remote_adapter(self):
        return SimpleNamespace(
            adapter_id="aid-remote",
            name="remote-api-openai-compat",
            transport="http",
            impl="user_api_keys",
            provider_mode=PROVIDER_REMOTE_ONLY,
            supported_roles=json.dumps(["researcher", "writer", "reviewer", "judge"]),
            capabilities=json.dumps([]),
            config=None,
        )

    def test_local_preferred_picks_local_adapter(self):
        plan = _plan()
        task = {"role": ROLE_RESEARCHER, "impact_level": "low"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[self._local_adapter(), self._remote_adapter()],
        ):
            result = resolve_execution_provider(None, plan, task)
        self.assertEqual(result["provider_mode"], PROVIDER_LOCAL_PREFERRED)
        self.assertEqual(result["adapter_name"], "local-llm-ollama")
        self.assertFalse(result["fallback_occurred"])
        self.assertIsNotNone(result["provider_payload"])

    def test_no_local_adapter_falls_back_to_remote(self):
        plan = _plan()
        task = {"role": ROLE_RESEARCHER, "impact_level": "low"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[self._remote_adapter()],
        ):
            result = resolve_execution_provider(None, plan, task)
        self.assertEqual(result["provider_mode"], PROVIDER_REMOTE_ONLY)
        self.assertTrue(result["fallback_occurred"])
        self.assertIn("fallback_no_adapter", result["selection_reason"])
        self.assertEqual(result["adapter_name"], "remote-api-openai-compat")

    def test_judge_does_not_fall_to_local(self):
        plan = _plan()
        task = {"role": ROLE_JUDGE, "impact_level": "low"}
        with patch(
            "app.services.coordinator_extensions.list_adapters",
            return_value=[self._local_adapter(), self._remote_adapter()],
        ):
            result = resolve_execution_provider(None, plan, task)
        self.assertEqual(result["provider_mode"], PROVIDER_REMOTE_ONLY)
        self.assertEqual(result["selection_reason"], "judge_forced_remote")
        self.assertEqual(result["adapter_name"], "remote-api-openai-compat")


if __name__ == "__main__":
    unittest.main()
