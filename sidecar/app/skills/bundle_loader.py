from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(slots=True)
class BundleManifest:
    skill_name: str
    version: str
    hash_value: str
    encryption_scheme: str
    signature: str | None = None


class ManifestVerifier(Protocol):
    def verify(self, manifest: BundleManifest, ciphertext: bytes) -> bool:
        """Return True when the manifest and ciphertext are trusted."""


class InMemoryPromptHandle(AbstractContextManager["InMemoryPromptHandle"]):
    """Best-effort memory-only handle for decrypted prompt text."""

    def __init__(self, plaintext: str) -> None:
        self._buffer = bytearray(plaintext.encode("utf-8"))

    @property
    def text(self) -> str:
        return self._buffer.decode("utf-8")

    def close(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
        return None


class SkillBundleLoader:
    """
    Bundle loader contract for desktop execution.

    This intentionally avoids any file-system write path. The caller is expected
    to provide ciphertext bytes from a DB or cache layer, verify the manifest,
    decrypt in memory, use the returned handle, and then immediately dispose it.
    """

    def __init__(self, verifier: ManifestVerifier) -> None:
        self._verifier = verifier

    def load_prompt(
        self,
        manifest: BundleManifest,
        ciphertext: bytes,
        decryptor: Callable[[bytes], str],
    ) -> InMemoryPromptHandle:
        if not self._verifier.verify(manifest, ciphertext):
            raise ValueError("bundle verification failed")

        plaintext = decryptor(ciphertext)
        if not isinstance(plaintext, str):
            raise TypeError("decryptor must return plaintext as str")

        return InMemoryPromptHandle(plaintext)
