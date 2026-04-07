"""Tests for OpenAICompatibleHttpProvider via httpx MockTransport."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import httpx

# Allow `from app.providers...` imports when running this file standalone.
_SIDECAR_ROOT = Path(__file__).resolve().parents[1]
if str(_SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_ROOT))

from app.providers.base import ProviderRequest  # noqa: E402
from app.providers.factory import create_provider  # noqa: E402
from app.providers.http_provider import OpenAICompatibleHttpProvider  # noqa: E402


def _make_provider_with_transport(handler) -> OpenAICompatibleHttpProvider:
    """Build a provider whose internal client uses a MockTransport."""
    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleHttpProvider(
        base_url="http://localhost:11434/v1",
        model="qwen2.5:14b",
        preflight=False,
    )

    # Monkey-patch httpx.Client construction inside provider.run by injecting
    # a custom Client subclass via a context manager replacement.
    original_run = provider.run

    def patched_run(request: ProviderRequest):
        # Re-implement minimal flow with the mock transport.
        # We rely on the provider's logic but swap the client.
        import httpx as _httpx

        real_client_cls = _httpx.Client

        class _PatchedClient(real_client_cls):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        _httpx.Client = _PatchedClient  # type: ignore[assignment]
        try:
            return original_run(request)
        finally:
            _httpx.Client = real_client_cls  # type: ignore[assignment]

    provider.run = patched_run  # type: ignore[method-assign]
    return provider


class HttpProviderTests(unittest.TestCase):
    def _request(self) -> ProviderRequest:
        return ProviderRequest(prompt="hello", model="qwen2.5:14b", metadata={})

    def test_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            return httpx.Response(
                200,
                json={
                    "model": "qwen2.5:14b",
                    "choices": [
                        {"message": {"content": "world"}, "finish_reason": "stop"}
                    ],
                    "usage": {"total_tokens": 12},
                },
            )

        provider = _make_provider_with_transport(handler)
        resp = provider.run(self._request())
        self.assertEqual(resp.status, "success")
        self.assertEqual(resp.output_text, "world")
        self.assertEqual(resp.tokens_used, 12)
        self.assertEqual(resp.token_accounting_source, "provider_usage")
        self.assertEqual(resp.provider_transport, "http")
        self.assertEqual(resp.provider_runtime, "http")
        self.assertEqual(resp.provider_impl, "http://localhost:11434/v1")

    def test_http_4xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        provider = _make_provider_with_transport(handler)
        resp = provider.run(self._request())
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "http_4xx")

    def test_http_5xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="boom")

        provider = _make_provider_with_transport(handler)
        resp = provider.run(self._request())
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "http_5xx")

    def test_connect_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        provider = _make_provider_with_transport(handler)
        resp = provider.run(self._request())
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "connect_error")

    def test_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        provider = _make_provider_with_transport(handler)
        resp = provider.run(self._request())
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "timeout")

    def test_empty_choices(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        provider = _make_provider_with_transport(handler)
        resp = provider.run(self._request())
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "missing_choices")


class PreflightTests(unittest.TestCase):
    def _request(self) -> ProviderRequest:
        return ProviderRequest(prompt="hello", model="qwen2.5-coder:14b", metadata={})

    def _provider(self) -> OpenAICompatibleHttpProvider:
        return OpenAICompatibleHttpProvider(
            base_url="http://localhost:11434/v1",
            model="qwen2.5-coder:14b",
            preflight=True,
        )

    def test_preflight_unreachable_short_circuits(self):
        from app.providers import http_provider as hp_mod

        def fake_list_models(base_url, timeout=5.0):
            return {"reachable": False, "models": [], "latency_ms": None, "error": "connect_error: refused"}

        chat_called = {"value": False}

        def fail_if_called(*args, **kwargs):
            chat_called["value"] = True
            raise AssertionError("chat endpoint should not be called when preflight fails")

        # Patch discovery.list_models inside the provider module's import path.
        from app.providers import discovery
        original = discovery.list_models
        discovery.list_models = fake_list_models
        try:
            provider = self._provider()
            # Also guard: if chat were attempted, httpx.Client would try to connect.
            # Patch httpx.Client to detect any chat call.
            import httpx as _httpx
            original_client = _httpx.Client
            _httpx.Client = fail_if_called  # type: ignore[assignment]
            try:
                resp = provider.run(self._request())
            finally:
                _httpx.Client = original_client  # type: ignore[assignment]
        finally:
            discovery.list_models = original

        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "connect_error")
        self.assertEqual(resp.retry_reason, "local_provider_unreachable")
        self.assertFalse(chat_called["value"])

    def test_preflight_model_missing(self):
        from app.providers import discovery

        def fake_list_models(base_url, timeout=5.0):
            return {
                "reachable": True,
                "models": ["llama3:8b"],
                "latency_ms": 12,
                "error": None,
            }

        original = discovery.list_models
        discovery.list_models = fake_list_models
        try:
            resp = self._provider().run(self._request())
        finally:
            discovery.list_models = original

        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "model_not_found")
        self.assertEqual(resp.retry_reason, "local_provider_model_missing")

    def test_preflight_ok_proceeds_to_chat(self):
        from app.providers import discovery

        def fake_list_models(base_url, timeout=5.0):
            return {
                "reachable": True,
                "models": ["qwen2.5-coder:14b", "llama3:8b"],
                "latency_ms": 8,
                "error": None,
            }

        def chat_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "qwen2.5-coder:14b",
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 5},
                },
            )

        original_list = discovery.list_models
        discovery.list_models = fake_list_models
        try:
            provider = _make_provider_with_transport(chat_handler)
            # _make_provider_with_transport disables preflight; re-enable for this test.
            provider._preflight = True
            provider._default_model = "qwen2.5-coder:14b"
            resp = provider.run(ProviderRequest(prompt="hi", model="qwen2.5-coder:14b", metadata={}))
        finally:
            discovery.list_models = original_list

        self.assertEqual(resp.status, "success")
        self.assertEqual(resp.output_text, "ok")


class DiscoveryTests(unittest.TestCase):
    def test_list_models_parses_openai_shape(self):
        from app.providers import discovery

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/models")
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "qwen2.5-coder:14b", "object": "model"},
                        {"id": "llama3:8b", "object": "model"},
                    ],
                },
            )

        transport = httpx.MockTransport(handler)
        original_client = httpx.Client

        class _PatchedClient(original_client):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        httpx.Client = _PatchedClient  # type: ignore[assignment]
        try:
            result = discovery.list_models("http://localhost:11434/v1")
        finally:
            httpx.Client = original_client  # type: ignore[assignment]

        self.assertTrue(result["reachable"])
        self.assertIn("qwen2.5-coder:14b", result["models"])
        self.assertIsNone(result["error"])

    def test_list_models_connect_error(self):
        from app.providers import discovery

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(handler)
        original_client = httpx.Client

        class _PatchedClient(original_client):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        httpx.Client = _PatchedClient  # type: ignore[assignment]
        try:
            result = discovery.list_models("http://localhost:11434/v1")
        finally:
            httpx.Client = original_client  # type: ignore[assignment]

        self.assertFalse(result["reachable"])
        self.assertEqual(result["models"], [])
        self.assertIn("connect_error", result["error"])


class FactoryTests(unittest.TestCase):
    def test_http_branch(self):
        provider = create_provider(
            "api_key",
            provider_payload={
                "transport": "http",
                "base_url": "http://localhost:11434/v1",
                "model": "qwen2.5:14b",
            },
        )
        self.assertIsInstance(provider, OpenAICompatibleHttpProvider)

    def test_http_missing_base_url(self):
        with self.assertRaises(ValueError):
            create_provider(
                "api_key",
                provider_payload={"transport": "http", "model": "qwen2.5:14b"},
            )

    def test_http_missing_model(self):
        with self.assertRaises(ValueError):
            create_provider(
                "api_key",
                provider_payload={
                    "transport": "http",
                    "base_url": "http://localhost:11434/v1",
                },
            )

    def test_cli_branch_unchanged(self):
        provider = create_provider("cli")
        self.assertEqual(provider.mode, "cli")

    def test_default_api_key_branch_unchanged(self):
        provider = create_provider("api_key")
        self.assertEqual(provider.mode, "api_key")


if __name__ == "__main__":
    unittest.main()
