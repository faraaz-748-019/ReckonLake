"""
Per-token envelope encryption using AES-256-GCM.

Each token gets a unique 256-bit Data Encryption Key (DEK) wrapped by a
Key-Encryption Key (KEK) supplied via a KEKProvider (OpenBao transit or
documented local fallback key service).

Crypto-shredding deletes the wrapped DEK for a token_id, rendering all
ciphertexts encrypted under that token permanently unreadable everywhere
(including immutable Bronze Delta/Parquet files) without rewriting history.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.key_service import KEKProvider, LocalKeyService


class CryptoShredError(Exception):
    """Raised when attempting to decrypt a shredded token."""


@runtime_checkable
class DEKStore(Protocol):
    def put(self, token_id: str, wrapped_dek: bytes, kek_nonce: bytes) -> None: ...
    def get(self, token_id: str) -> tuple[bytes, bytes] | None: ...
    def delete(self, token_id: str) -> None: ...
    def has_key(self, token_id: str) -> bool: ...


class InMemoryDEKStore:
    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, bytes]] = {}

    def put(self, token_id: str, wrapped_dek: bytes, kek_nonce: bytes) -> None:
        self._store[token_id] = (wrapped_dek, kek_nonce)

    def get(self, token_id: str) -> tuple[bytes, bytes] | None:
        return self._store.get(token_id)

    def delete(self, token_id: str) -> None:
        if token_id in self._store:
            w, n = self._store[token_id]
            self._store[token_id] = (b"\x00" * len(w), b"\x00" * len(n))
            del self._store[token_id]

    def has_key(self, token_id: str) -> bool:
        return token_id in self._store


class FileKeyStore:
    """JSON-backed wrapped-DEK keystore for local CLI and demo persistence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        return dict(json.loads(self.path.read_text(encoding="utf-8")))

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def put(self, token_id: str, wrapped_dek: bytes, kek_nonce: bytes) -> None:
        data = self._load()
        data[token_id] = {
            "wrapped_dek": base64.b64encode(wrapped_dek).decode(),
            "kek_nonce": base64.b64encode(kek_nonce).decode(),
        }
        self._save(data)

    def get(self, token_id: str) -> tuple[bytes, bytes] | None:
        data = self._load()
        rec = data.get(token_id)
        if rec is None:
            return None
        return (
            base64.b64decode(rec["wrapped_dek"]),
            base64.b64decode(rec["kek_nonce"]),
        )

    def delete(self, token_id: str) -> None:
        data = self._load()
        if token_id in data:
            del data[token_id]
            self._save(data)

    def has_key(self, token_id: str) -> bool:
        return token_id in self._load()


class EnvelopeEncryptor:
    """AES-256-GCM envelope encryptor with per-token DEKs and pluggable KEK provider."""

    def __init__(
        self,
        kek: bytes | None = None,
        kek_provider: KEKProvider | None = None,
        dek_store: DEKStore | None = None,
    ) -> None:
        if kek_provider is not None:
            self._provider = kek_provider
        elif kek is not None:
            self._provider = LocalKeyService(kek=kek)
        else:
            self._provider = LocalKeyService()
        self._dek_store: DEKStore = dek_store if dek_store is not None else InMemoryDEKStore()

    def encrypt(self, plaintext: str, token_id: str) -> dict[str, str]:
        """Encrypt *plaintext* with a fresh 256-bit DEK and wrap the DEK with the KEK."""
        dek = os.urandom(32)
        nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), token_id.encode("utf-8"))

        wrapped_dek, kek_nonce = self._provider.wrap_dek(dek, b"dek-wrap")
        self._dek_store.put(token_id, wrapped_dek, kek_nonce)

        return {
            "token_id": token_id,
            "ciphertext": base64.b64encode(ciphertext).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "wrapped_dek": base64.b64encode(wrapped_dek).decode(),
            "kek_nonce": base64.b64encode(kek_nonce).decode(),
        }

    def decrypt(self, envelope: dict[str, str]) -> str:
        """Decrypt an envelope. Raises CryptoShredError if the token's DEK was shredded."""
        token_id = envelope["token_id"]
        stored = self._dek_store.get(token_id)
        if stored is None:
            raise CryptoShredError(
                f"DEK for token_id '{token_id}' has been shredded or was never stored. "
                "Data is permanently unreadable."
            )

        wrapped_dek, kek_nonce = stored
        dek = self._provider.unwrap_dek(wrapped_dek, kek_nonce, b"dek-wrap")

        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
        plaintext_bytes = AESGCM(dek).decrypt(nonce, ciphertext, token_id.encode("utf-8"))
        return plaintext_bytes.decode("utf-8")

    def shred(self, token_id: str) -> None:
        """Delete the DEK for *token_id* (crypto-shredding)."""
        self._dek_store.delete(token_id)

    def has_key(self, token_id: str) -> bool:
        """Return True if the DEK for *token_id* is still active."""
        return self._dek_store.has_key(token_id)
