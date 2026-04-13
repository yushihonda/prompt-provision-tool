"""Structured provider execution errors used by runtime fallback layer.

These exceptions exist so the orchestration layer can decide whether a
local provider failure is fallback-eligible without inspecting raw
ProviderResponse fields. They are deliberately decoupled from any single
provider implementation so vLLM/LM Studio/llama-cpp can reuse them.
"""
from __future__ import annotations

from typing import Iterable

from .base import ProviderResponse


class ProviderExecutionError(Exception):
    def __init__(
        self,
        reason: str,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status_code = status_code


class RecoverableProviderError(ProviderExecutionError):
    """Recoverable failure: caller may retry with another provider."""


class NonRecoverableProviderError(ProviderExecutionError):
    """Non-recoverable failure: do not retry."""


# Stable machine-readable error_code values that are eligible for runtime
# fallback (local -> remote retry under local_preferred policy).
RECOVERABLE_ERROR_CODES: frozenset[str] = frozenset(
    {
        "connect_error",
        "timeout",
        "http_5xx",
        "http_error",
        "malformed_json",
        "missing_choices",
        "empty_content",
        "model_not_found",
        "transport_error",
    }
)


def is_recoverable_error_code(error_code: str | None) -> bool:
    if not error_code:
        return False
    return error_code in RECOVERABLE_ERROR_CODES


def classify_provider_response(
    response: ProviderResponse,
    *,
    extra_recoverable: Iterable[str] = (),
) -> ProviderExecutionError | None:
    """Convert a non-success ProviderResponse into a structured exception.

    Returns None for successful responses. Returns a Recoverable or
    NonRecoverable exception otherwise so the runtime fallback layer can
    decide what to do without re-parsing error_code strings.
    """
    if response.status == "success":
        return None
    code = response.error_code or "unknown_error"
    message = response.error_message or "provider failed"
    if code in RECOVERABLE_ERROR_CODES or code in set(extra_recoverable):
        return RecoverableProviderError(reason=code, message=message)
    return NonRecoverableProviderError(reason=code, message=message)
