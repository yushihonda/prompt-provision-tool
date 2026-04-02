from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptProtectionPolicy:
    memory_only_decryption: bool = True
    allow_plaintext_disk_write: bool = False
    allow_temp_files: bool = False
    allow_plaintext_logs: bool = False
    prefer_stdin_for_cli_mode: bool = True


def redact_for_logs(text: str, limit: int = 32) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return "[REDACTED]"
    return f"{text[:limit]}...[REDACTED]"
