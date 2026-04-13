from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderRequest:
    prompt: str
    model: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderResponse:
    status: str
    output_text: str
    provider_mode: str
    provider_transport: str
    provider_adapter: str
    provider_runtime: str
    provider_impl: str
    model: str
    tokens_used: int | None = None
    token_accounting_source: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_reason: str | None = None


class LLMProvider(ABC):
    mode: str

    @abstractmethod
    def run(self, request: ProviderRequest) -> ProviderResponse:
        """Execute a single provider request."""
