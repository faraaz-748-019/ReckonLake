"""Unit tests for tokenization, envelope encryption, crypto-shredding, audit chain, and RBAC."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from security.audit_chain import AuditChain
from security.envelope import CryptoShredError, EnvelopeEncryptor, FileKeyStore
from security.policies import Permission, Role, is_allowed
from security.shred import shred_token
from security.tokenizer import EnvKeySource, Tokenizer


@pytest.mark.unit
def test_tokenize_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKENIZER_HMAC_KEY", "test-secret-hmac-key-32-bytes-ok")
    tok = Tokenizer(EnvKeySource())
    t1 = tok.tokenize_vpa("user1@okaxis")
    t2 = tok.tokenize_vpa("user1@okaxis")
    assert t1 == t2
    assert len(t1) == 64
    assert tok.tokenize_vpa("user1@okaxis") != tok.tokenize_phone("user1@okaxis")


@pytest.mark.unit
def test_envelope_encrypt_decrypt_and_crypto_shred(tmp_path: Path) -> None:
    kek = os.urandom(32)
    ks_path = tmp_path / "keystore.json"
    audit_path = tmp_path / "audit.json"

    enc = EnvelopeEncryptor(kek=kek, dek_store=FileKeyStore(ks_path))
    env = enc.encrypt("9876543210", token_id="tok_phone_1")
    assert "9876543210" not in env["ciphertext"]
    assert enc.decrypt(env) == "9876543210"

    shred_token("tok_phone_1", ks_path, audit_path, actor="privacy-officer")
    with pytest.raises(CryptoShredError):
        enc.decrypt(env)

    chain = AuditChain.load(audit_path)
    valid, bad_idx = chain.verify()
    assert valid and bad_idx is None


@pytest.mark.unit
def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    chain = AuditChain()
    chain.append("KEY_ACCESS", "spark", "token:1", {"op": "read"})
    chain.append("ROLE_CHANGE", "admin", "analyst_masked", {"grant": "SELECT"})
    chain.append("SHREDDING", "privacy", "token:1", {"reason": "DPDP erasure"})

    ok, idx = chain.verify()
    assert ok and idx is None

    # Tamper entry 1 details without updating hash
    chain._entries[1].details["grant"] = "ALL"
    ok2, idx2 = chain.verify()
    assert not ok2 and idx2 == 1


@pytest.mark.unit
def test_rbac_least_privilege() -> None:
    assert is_allowed(Role.ANALYST, Permission.GOLD_READ)
    assert not is_allowed(Role.ANALYST, Permission.BRONZE_WRITE)
    assert not is_allowed(Role.ANALYST, Permission.SHRED_EXECUTE)
    assert is_allowed(Role.AUDITOR, Permission.AUDIT_READ)
    assert not is_allowed(Role.AUDITOR, Permission.KEYS_MANAGE)
    assert is_allowed(Role.SHREDDER, Permission.SHRED_EXECUTE)
    assert not is_allowed(Role.SHREDDER, Permission.GOLD_READ)
