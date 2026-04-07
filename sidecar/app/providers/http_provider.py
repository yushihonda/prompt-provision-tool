from __future__ import annotations

import json
from typing import Any

import httpx

from .base import LLMProvider, ProviderRequest, ProviderResponse


class OpenAICompatibleHttpProvider(LLMProvider):
    """Generic OpenAI-compatible HTTP provider.

    First concrete target: Ollama at http://localhost:11434/v1.
    Future-compatible: vLLM, LM Studio, llama-cpp-python server.
    Phase 1 path: POST {base_url}/chat/completions (non-streaming).
    """

    mode = "http"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = 120.0,
        adapter_name: str = "local-llm-ollama",
        provider_mode_label: str = "local_preferred",
        preflight: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = model
        self._api_key = api_key
        self._timeout = timeout
        self._adapter_name = adapter_name
        self._provider_mode_label = provider_mode_label
        self._preflight = preflight

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _build_response(
        self,
        *,
        status: str,
        output_text: str,
        model: str,
        tokens_used: int | None = None,
        token_accounting_source: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_reason: str | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            status=status,
            output_text=output_text,
            provider_mode=self._provider_mode_label,
            provider_transport="http",
            provider_adapter=self._adapter_name,
            provider_runtime="http",
            provider_impl=self._base_url,
            model=model,
            tokens_used=tokens_used,
            token_accounting_source=token_accounting_source,
            error_code=error_code,
            error_message=error_message,
            retry_reason=retry_reason,
        )

    def _do_preflight(self, model: str) -> ProviderResponse | None:
        """Run a fast discovery probe before the chat call.

        Returns a ProviderResponse on failure (caller short-circuits) or
        None on success (caller proceeds to /chat/completions).
        """
        from .discovery import list_models

        result = list_models(
            self._base_url,
            timeout=min(5.0, self._timeout),
        )
        if not result["reachable"]:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="connect_error",
                error_message=result.get("error") or "preflight unreachable",
                retry_reason="local_provider_unreachable",
            )
        if model not in result["models"]:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="model_not_found",
                error_message=(
                    f"model {model} not present at {self._base_url} "
                    f"(available: {len(result['models'])})"
                ),
                retry_reason="local_provider_model_missing",
            )
        return None

    def run(self, request: ProviderRequest) -> ProviderResponse:
        model = request.model or self._default_model
        if self._preflight:
            pre = self._do_preflight(model)
            if pre is not None:
                return pre
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
        }
        url = f"{self._base_url}/chat/completions"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=body, headers=self._headers())
        except httpx.ConnectError as exc:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="connect_error",
                error_message=str(exc),
                retry_reason="local_provider_unreachable",
            )
        except httpx.TimeoutException as exc:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="timeout",
                error_message=str(exc),
                retry_reason="local_provider_timeout",
            )
        except httpx.HTTPError as exc:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="http_error",
                error_message=str(exc),
                retry_reason="local_provider_http_error",
            )

        if resp.status_code >= 500:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="http_5xx",
                error_message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                retry_reason="local_provider_server_error",
            )
        if resp.status_code >= 400:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="http_4xx",
                error_message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                retry_reason="local_provider_client_error",
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="malformed_json",
                error_message=str(exc),
                retry_reason="local_provider_bad_response",
            )

        choices = data.get("choices") or []
        if not choices:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="missing_choices",
                error_message="response had no choices",
                retry_reason="local_provider_empty",
            )
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if not content:
            return self._build_response(
                status="error",
                output_text="",
                model=model,
                error_code="empty_content",
                error_message="response choice had empty content",
                retry_reason="local_provider_empty",
            )

        usage = data.get("usage") or {}
        tokens_used = usage.get("total_tokens")
        token_source = "provider_usage" if tokens_used is not None else "unavailable"
        actual_model = data.get("model") or model

        return self._build_response(
            status="success",
            output_text=content,
            model=actual_model,
            tokens_used=tokens_used,
            token_accounting_source=token_source,
        )
