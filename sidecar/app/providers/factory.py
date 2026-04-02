from __future__ import annotations

from .api_key_provider import ApiKeyProvider
from .base import LLMProvider
from .cli_provider import CliProvider


def create_provider(engine_mode: str) -> LLMProvider:
    if engine_mode == "cli":
        return CliProvider()
    return ApiKeyProvider()
