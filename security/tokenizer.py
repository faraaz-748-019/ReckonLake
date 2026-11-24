"""
Deterministic HMAC tokenizer for PII fields with pluggable key source.
Supports EnvKeySource, OpenBaoKeyService, and LocalKeyService.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class KeySource(Protocol):
    """Protocol for HMAC key retrieval."""

    def get_key(self, key_id: str) -> bytes:
        """Return the HMAC key bytes for the given key_id."""
        ...


class EnvKeySource:
    """Local fallback: reads TOKENIZER_HMAC_KEY from environment or secret file."""

    def get_key(self, key_id: str) -> bytes:
        key_file = os.environ.get("TOKENIZER_HMAC_KEY_FILE", "")
        if key_file and os.path.exists(key_file):
            with open(key_file, encoding="utf-8") as fh:
                key = fh.read().strip()
        else:
            key = os.environ.get("TOKENIZER_HMAC_KEY", "")
        if not key:
            raise ValueError(
                "TOKENIZER_HMAC_KEY not set. "
                "Export a 32-byte hex secret or use OpenBao in production."
            )
        return hmac.new(key.encode("utf-8"), key_id.encode("utf-8"), hashlib.sha256).digest()


class ProviderKeySource:
    """Adapter bridging key_service.KEKProvider (e.g. OpenBaoKeyService) to KeySource."""

    def __init__(self, provider: object) -> None:
        self._provider = provider

    def get_key(self, key_id: str) -> bytes:
        return bytes(self._provider.get_hmac_key(key_id))  # type: ignore[attr-defined]


class Tokenizer:
    """Deterministic HMAC-SHA256 tokenizer for PII fields at the Bronze boundary."""

    def __init__(self, key_source: KeySource) -> None:
        self._key_source = key_source

    def tokenize(self, value: str, field_type: str) -> str:
        """Produce a 64-character hex HMAC-SHA256 token."""
        if not value:
            raise ValueError("Cannot tokenize an empty value")
        key = self._key_source.get_key(f"token:{field_type}")
        return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def tokenize_vpa(self, vpa: str) -> str:
        return self.tokenize(vpa, "vpa")

    def tokenize_phone(self, phone: str) -> str:
        return self.tokenize(phone, "phone")

    def tokenize_account(self, account: str) -> str:
        return self.tokenize(account, "account")
