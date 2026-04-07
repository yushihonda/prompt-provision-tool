from __future__ import annotations

from typing import Any

from .api_key_provider import ApiKeyProvider
from .base import LLMProvider
from .cli_provider import CliProvider
from .http_provider import OpenAICompatibleHttpProvider


def create_provider(
    engine_mode: str,
    provider_payload: dict[str, Any] | None = None,
) -> LLMProvider:
    if provider_payload and provider_payload.get("transport") == "http":
        base_url = provider_payload.get("base_url")
        model = provider_payload.get("model")
        if not base_url:
            raise ValueError("provider_payload.base_url is required for http transport")
        if not model:
            raise ValueError("provider_payload.model is required for http transport")
        return OpenAICompatibleHttpProvider(
            base_url=base_url,
            model=model,
            api_key=provider_payload.get("api_key"),
            timeout=float(provider_payload.get("timeout", 120.0)),
            adapter_name=provider_payload.get("adapter_name", "local-llm-ollama"),
            provider_mode_label=provider_payload.get("provider_mode", "local_preferred"),
        )
    if engine_mode == "cli":
        return CliProvider()
    return ApiKeyProvider()
