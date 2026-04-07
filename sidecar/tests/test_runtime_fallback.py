"""Tests for _run_with_runtime_fallback in real_execution.

These tests don't go over real HTTP — they monkeypatch
_execute_http_provider so each "provider attempt" returns a
ProviderResponse the test controls. That keeps the focus on the runtime
fallback decision logic itself.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_SIDECAR_ROOT = Path(__file__).resolve().parents[1]
if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

from app.providers.base import ProviderResponse  # noqa: E402
from app.providers.errors import RecoverableProviderError  # noqa: E402
from app import real_execution  # noqa: E402


def _ok_response(adapter_name: str, model: str = "qwen2.5:14b") -> ProviderResponse:
    return ProviderResponse(
        status="success",
        output_text="hello",
        provider_mode="local_preferred",
        provider_transport="http",
        provider_adapter=adapter_name,
        provider_runtime="http",
        provider_impl="http://localhost:11434/v1",
        model=model,
        tokens_used=10,
        token_accounting_source="provider_usage",
    )


def _err_response(error_code: str, adapter_name: str = "local-llm-ollama") -> ProviderResponse:
    return ProviderResponse(
        status="error",
        output_text="",
        provider_mode="local_preferred",
        provider_transport="http",
        provider_adapter=adapter_name,
        provider_runtime="http",
        provider_impl="http://localhost:11434/v1",
        model="qwen2.5:14b",
        error_code=error_code,
        error_message=f"simulated {error_code}",
    )


LOCAL_PAYLOAD = {
    "transport": "http",
    "base_url": "http://localhost:11434/v1",
    "model": "qwen2.5:14b",
    "adapter_id": "aid-local",
    "adapter_name": "local-llm-ollama",
    "provider_mode_selected": "local_preferred",
    "provider_selection_reason": "low_impact_local",
}

REMOTE_PAYLOAD = {
    "transport": "http",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "adapter_id": "aid-remote",
    "adapter_name": "remote-api-openai-compat",
    "provider_mode_selected": "remote_only",
    "provider_selection_reason": "runtime_fallback_remote",
}


class RuntimeFallbackTests(unittest.TestCase):
    def setUp(self):
        self._calls: list[dict] = []
        self._original = real_execution._execute_http_provider

    def tearDown(self):
        real_execution._execute_http_provider = self._original

    def _install_responses(self, responses):
        """responses: list of ProviderResponse, popped in call order."""
        queue = list(responses)

        def fake(payload, *, final_prompt, bundle_model, execution_id):
            self._calls.append(payload)
            return queue.pop(0)

        real_execution._execute_http_provider = fake

    def _run(self, fallback_payload=REMOTE_PAYLOAD, primary=LOCAL_PAYLOAD):
        return asyncio.run(
            real_execution._run_with_runtime_fallback(
                provider_payload=primary,
                fallback_provider_payload=fallback_payload,
                final_prompt="hi",
                bundle_model="qwen2.5:14b",
                execution_id=1,
            )
        )

    def test_1_local_success(self):
        self._install_responses([_ok_response("local-llm-ollama")])
        response, meta = self._run()
        self.assertEqual(response.status, "success")
        self.assertFalse(meta["fallback_applied"])
        self.assertEqual(meta["provider_attempt_count"], 1)
        self.assertEqual(meta["selected_adapter_id"], "aid-local")
        self.assertEqual(meta["actual_adapter_id"], "aid-local")
        self.assertEqual(len(self._calls), 1)

    def test_2_local_connection_refused_falls_back(self):
        self._install_responses(
            [_err_response("connect_error"), _ok_response("remote", model="gpt-4o-mini")]
        )
        response, meta = self._run()
        self.assertEqual(response.status, "success")
        self.assertTrue(meta["fallback_applied"])
        self.assertEqual(meta["fallback_reason"], "connect_error")
        self.assertEqual(meta["provider_attempt_count"], 2)
        self.assertEqual(meta["selected_adapter_id"], "aid-local")
        self.assertEqual(meta["actual_adapter_id"], "aid-remote")
        self.assertEqual(meta["fallback_from_adapter_id"], "aid-local")
        self.assertEqual(meta["fallback_to_adapter_id"], "aid-remote")
        self.assertEqual(len(self._calls), 2)

    def test_3_local_timeout_falls_back(self):
        self._install_responses(
            [_err_response("timeout"), _ok_response("remote")]
        )
        response, meta = self._run()
        self.assertEqual(response.status, "success")
        self.assertTrue(meta["fallback_applied"])
        self.assertEqual(meta["fallback_reason"], "timeout")

    def test_4_local_malformed_response_falls_back(self):
        self._install_responses(
            [_err_response("malformed_json"), _ok_response("remote")]
        )
        _, meta = self._run()
        self.assertTrue(meta["fallback_applied"])
        self.assertEqual(meta["fallback_reason"], "malformed_json")

    def test_5_local_only_does_not_fall_back(self):
        local_only_payload = dict(LOCAL_PAYLOAD)
        local_only_payload["provider_mode_selected"] = "local_only"
        self._install_responses([_err_response("connect_error")])
        response, meta = self._run(primary=local_only_payload, fallback_payload=REMOTE_PAYLOAD)
        self.assertEqual(response.status, "error")
        self.assertFalse(meta["fallback_applied"])
        self.assertEqual(meta["provider_attempt_count"], 1)
        self.assertEqual(len(self._calls), 1)

    def test_6_local_preferred_without_fallback_payload(self):
        self._install_responses([_err_response("connect_error")])
        response, meta = self._run(fallback_payload=None)
        self.assertEqual(response.status, "error")
        self.assertFalse(meta["fallback_applied"])
        self.assertEqual(len(self._calls), 1)

    def test_7_remote_selected_directly_no_fallback_path(self):
        remote_primary = dict(REMOTE_PAYLOAD)
        # Even if fallback payload is supplied, remote selected mode
        # must not trigger any fallback path.
        self._install_responses([_ok_response("remote")])
        _, meta = self._run(primary=remote_primary, fallback_payload=REMOTE_PAYLOAD)
        self.assertFalse(meta["fallback_applied"])
        self.assertEqual(meta["provider_attempt_count"], 1)
        self.assertEqual(meta["actual_adapter_id"], "aid-remote")

    def test_preflight_unreachable_meta(self):
        self._install_responses(
            [_err_response("connect_error"), _ok_response("remote", model="gpt-4o-mini")]
        )
        _, meta = self._run()
        self.assertEqual(meta["preflight_status"], "unreachable")
        self.assertEqual(meta["local_error_reason"], "connect_error")
        self.assertEqual(meta["local_model_requested"], "qwen2.5:14b")

    def test_preflight_model_missing_meta(self):
        self._install_responses(
            [_err_response("model_not_found"), _ok_response("remote")]
        )
        _, meta = self._run()
        self.assertEqual(meta["preflight_status"], "model_missing")
        self.assertEqual(meta["local_error_reason"], "model_not_found")

    def test_local_success_preflight_ok(self):
        self._install_responses([_ok_response("local-llm-ollama")])
        _, meta = self._run()
        self.assertEqual(meta["preflight_status"], "ok")
        self.assertIsNone(meta["local_error_reason"])
        self.assertEqual(meta["local_model_requested"], "qwen2.5:14b")

    def test_remote_only_omits_local_model_requested(self):
        remote_primary = dict(REMOTE_PAYLOAD)
        self._install_responses([_ok_response("remote")])
        _, meta = self._run(primary=remote_primary, fallback_payload=REMOTE_PAYLOAD)
        self.assertEqual(meta["preflight_status"], "ok")
        self.assertIsNone(meta["local_model_requested"])

    def test_combined_failure_records_both_attempts(self):
        self._install_responses(
            [_err_response("connect_error"), _err_response("http_5xx")]
        )
        response, meta = self._run()
        self.assertEqual(response.status, "error")
        self.assertTrue(meta["fallback_applied"])
        self.assertEqual(meta["fallback_reason"], "connect_error")
        self.assertEqual(meta["provider_attempt_count"], 2)
        self.assertIn("local_failed", response.error_message)
        self.assertIn("remote_failed", response.error_message)


if __name__ == "__main__":
    unittest.main()
