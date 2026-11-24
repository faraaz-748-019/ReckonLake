"""
ReconLake security module.

Provides:
- Deterministic HMAC tokenization for PII fields (tokenizer.py)
- Per-token envelope encryption with AES-256-GCM (envelope.py)
- Tamper-evident hash-chained audit log (audit_chain.py)
- RBAC policies and access control definitions (policies.py)

Phase 8 integration point: swap EnvKeySource for an OpenBao-backed KeySource,
and swap local KEK generation for OpenBao transit encryption.
"""

from .audit_chain import AuditChain, AuditEntry
from .envelope import EnvelopeEncryptor
from .policies import ROLE_PERMISSIONS, Permission, Role, is_allowed
from .tokenizer import EnvKeySource, KeySource, Tokenizer

__all__ = [
    "Tokenizer",
    "EnvKeySource",
    "KeySource",
    "EnvelopeEncryptor",
    "AuditChain",
    "AuditEntry",
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "is_allowed",
]
