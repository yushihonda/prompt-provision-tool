from __future__ import annotations

from .base import LLMProvider, ProviderRequest, ProviderResponse


class ApiKeyProvider(LLMProvider):
    mode = "api_key"

    def run(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            status="success",
            output_text=(
                f"[API Key Mode] model={request.model} "
                f"prompt={request.prompt[:80]}"
            ),
            provider_mode=self.mode,
            provider_transport="sdk",
            provider_adapter="none",
            provider_runtime="python",
            provider_impl="sdk_execute_bundle",
            model=request.model,
            tokens_used=0,
            token_accounting_source="unavailable",
            error_code=None,
            error_message=None,
            retry_reason=None,
        )
