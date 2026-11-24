"""
Key-Encryption Key (KEK) & HMAC key provider abstraction.

Supports:
  1. LocalKeyService: file/env-backed fallback key service for laptop usage.
  2. OpenBaoKeyService: OpenBao (Vault-compatible) transit/KV integration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class KEKProvider(Protocol):
    """Protocol for Key-Encryption Key wrapping/unwrapping and HMAC key lookup."""

    def wrap_dek(self, dek: bytes, context: bytes = b"dek-wrap") -> tuple[bytes, bytes]:
        """Wrap a 32-byte DEK. Returns (wrapped_dek, nonce_or_metadata)."""
        ...

    def unwrap_dek(self, wrapped_dek: bytes, nonce: bytes, context: bytes = b"dek-wrap") -> bytes:
        """Unwrap and return the 32-byte DEK."""
        ...

    def get_hmac_key(self, key_id: str) -> bytes:
        """Return an HMAC key for deterministic tokenization."""
        ...


class LocalKeyService:
    """
    Documented local fallback key service for offline / laptop execution.
    Uses AES-256-GCM with a local 32-byte KEK (from argument, secret file, or env).
    """

    def __init__(self, kek: bytes | None = None, hmac_master: bytes | None = None) -> None:
        if kek is not None:
            if len(kek) != 32:
                raise ValueError("KEK must be 32 bytes")
            self._kek = kek
        else:
            env_kek = self._read_secret("ENVELOPE_KEK", "ENVELOPE_KEK_FILE")
            if env_kek:
                self._kek = hashlib.sha256(env_kek.encode()).digest()
            else:
                # Deterministic dev-only fallback if no env configured
                self._kek = hashlib.sha256(b"reconlake-local-dev-kek-only").digest()

        if hmac_master is not None:
            self._hmac_master = hmac_master
        else:
            env_hmac = self._read_secret("TOKENIZER_HMAC_KEY", "TOKENIZER_HMAC_KEY_FILE")
            self._hmac_master = (
                env_hmac.encode() if env_hmac else b"reconlake-local-dev-hmac-key-only"
            )

    @staticmethod
    def _read_secret(env_var: str, file_var: str) -> str:
        fpath = os.environ.get(file_var)
        if fpath and Path(fpath).exists():
            return Path(fpath).read_text(encoding="utf-8").strip()
        return os.environ.get(env_var, "").strip()

    def wrap_dek(self, dek: bytes, context: bytes = b"dek-wrap") -> tuple[bytes, bytes]:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        wrapped = AESGCM(self._kek).encrypt(nonce, dek, context)
        return wrapped, nonce

    def unwrap_dek(self, wrapped_dek: bytes, nonce: bytes, context: bytes = b"dek-wrap") -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(self._kek).decrypt(nonce, wrapped_dek, context)

    def get_hmac_key(self, key_id: str) -> bytes:
        return hmac.new(self._hmac_master, key_id.encode(), hashlib.sha256).digest()


class OpenBaoKeyService:
    """
    OpenBao Transit Engine key provider with automatic fallback to LocalKeyService
    if OpenBao is unreachable in laptop dev setups.
    """

    def __init__(
        self,
        addr: str | None = None,
        token: str | None = None,
        transit_key: str = "reconlake-kek",
        fallback: LocalKeyService | None = None,
    ) -> None:
        self.addr: str = (addr or os.environ.get("OPENBAO_ADDR") or "http://127.0.0.1:8200").rstrip("/")
        self.token: str = token or os.environ.get("OPENBAO_TOKEN") or ""
        self.transit_key = transit_key
        self.fallback = fallback or LocalKeyService()

    def _headers(self) -> dict[str, str]:
        return {"X-Vault-Token": self.token}

    def wrap_dek(self, dek: bytes, context: bytes = b"dek-wrap") -> tuple[bytes, bytes]:
        if not self.token:
            return self.fallback.wrap_dek(dek, context)
        try:
            payload = {
                "plaintext": base64.b64encode(dek).decode(),
                "context": base64.b64encode(context).decode(),
            }
            resp = httpx.post(
                f"{self.addr}/v1/transit/encrypt/{self.transit_key}",
                headers=self._headers(),
                json=payload,
                timeout=2.0,
            )
            resp.raise_for_status()
            ciphertext = resp.json()["data"]["ciphertext"].encode()
            return ciphertext, b"openbao-transit"
        except Exception:
            return self.fallback.wrap_dek(dek, context)

    def unwrap_dek(self, wrapped_dek: bytes, nonce: bytes, context: bytes = b"dek-wrap") -> bytes:
        if nonce == b"openbao-transit" and self.token:
            resp = httpx.post(
                f"{self.addr}/v1/transit/decrypt/{self.transit_key}",
                headers=self._headers(),
                json={
                    "ciphertext": wrapped_dek.decode(),
                    "context": base64.b64encode(context).decode(),
                },
                timeout=2.0,
            )
            resp.raise_for_status()
            return base64.b64decode(resp.json()["data"]["plaintext"])
        return self.fallback.unwrap_dek(wrapped_dek, nonce, context)

    def get_hmac_key(self, key_id: str) -> bytes:
        if not self.token:
            return self.fallback.get_hmac_key(key_id)
        try:
            resp = httpx.get(
                f"{self.addr}/v1/secret/data/reconlake/{key_id}",
                headers=self._headers(),
                timeout=2.0,
            )
            if resp.status_code == 200:
                val = resp.json()["data"]["data"]["key"]
                return json.dumps(val).encode() if not isinstance(val, str) else val.encode()
        except Exception as exc:
            logging.debug("OpenBao unreachable, falling back to LocalKeyService: %s", exc)
        return self.fallback.get_hmac_key(key_id)
