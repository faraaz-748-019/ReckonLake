"""
Tamper-evident audit log using SHA-256 hash chaining.

Each entry includes:
- The SHA-256 hash of the previous entry (prev_hash), forming a chain.
- Its own SHA-256 hash (entry_hash), computed over all fields including prev_hash.

Any post-write modification to an entry breaks the chain: verify() detects
both a modified entry (its hash no longer matches entry_hash) and a broken
link (its prev_hash no longer matches the predecessor's entry_hash).

Production notes:
- Persist entries to an append-only table where UPDATE and DELETE are revoked.
- Periodically anchor the chain head hash in a write-once store (e.g. a public
  blockchain or a notary service) for external auditability.
- Use a database sequence for timestamps to prevent replay under clock skew.

Event types:
    KEY_ACCESS              A data key was accessed (decrypt, re-wrap).
    ROLE_CHANGE             A subject's RBAC role was assigned or revoked.
    EXCEPTION_QUEUE_CHANGE  A record was added to / removed from the exception queue.
    SHREDDING               A DEK was shredded (crypto-deletion).
    POLICY_CHANGE           An access policy was updated.
    DATA_ACCESS             A PII field was accessed by a human operator.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    """
    A single immutable audit log entry.

    Fields included in the hash (and therefore tamper-evident):
        event_type, actor, resource, details, timestamp, prev_hash
    """

    event_type: str  # KEY_ACCESS | ROLE_CHANGE | EXCEPTION_QUEUE_CHANGE | SHREDDING | POLICY_CHANGE | DATA_ACCESS
    actor: str       # service account or human operator identity
    resource: str    # the target resource (table, token_id, role, etc.)
    details: dict    # structured context; must be JSON-serialisable
    timestamp: float = field(default_factory=time.time)
    prev_hash: str = ""
    entry_hash: str = ""

    _VALID_EVENT_TYPES = frozenset(
        {"KEY_ACCESS", "ROLE_CHANGE", "EXCEPTION_QUEUE_CHANGE",
         "SHREDDING", "POLICY_CHANGE", "DATA_ACCESS"}
    )

    def __post_init__(self) -> None:
        if self.event_type not in self._VALID_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{self.event_type}'. "
                f"Valid types: {sorted(self._VALID_EVENT_TYPES)}"
            )

    def compute_hash(self) -> str:
        """
        Compute the SHA-256 hash of this entry's canonical JSON representation.

        Fields are sorted for reproducibility across Python versions / platforms.
        """
        content = json.dumps(
            {
                "event_type": self.event_type,
                "actor": self.actor,
                "resource": self.resource,
                "details": self.details,
                "timestamp": self.timestamp,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()


class AuditChain:
    """
    Append-only, hash-chained audit log.

    Thread-safety: not thread-safe by design; callers should use a lock or
    route all writes through a single async worker in production.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def append(
        self,
        event_type: str,
        actor: str,
        resource: str,
        details: dict,
    ) -> AuditEntry:
        """
        Append a new entry and return it (with entry_hash populated).

        The entry is linked to the previous entry via prev_hash before its
        own hash is computed, so the chain is unbreakable by construction.
        """
        prev_hash = self._entries[-1].entry_hash if self._entries else ""
        entry = AuditEntry(
            event_type=event_type,
            actor=actor,
            resource=resource,
            details=details,
            prev_hash=prev_hash,
        )
        entry.entry_hash = entry.compute_hash()
        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Read / verify path
    # ------------------------------------------------------------------

    def verify(self) -> tuple[bool, int | None]:
        """
        Walk the chain and verify integrity.

        Returns:
            (True, None)    — chain is intact.
            (False, index)  — entry at *index* has been tampered with.

        Two checks per entry:
            1. entry.entry_hash == entry.compute_hash()   (self-consistency)
            2. entry.prev_hash  == entries[i-1].entry_hash (chain linkage)
        """
        for i, entry in enumerate(self._entries):
            expected_hash = entry.compute_hash()
            if entry.entry_hash != expected_hash:
                return False, i
            if i > 0 and entry.prev_hash != self._entries[i - 1].entry_hash:
                return False, i
        return True, None

    def head_hash(self) -> str:
        """Return the hash of the most recent entry, or '' if the chain is empty."""
        return self._entries[-1].entry_hash if self._entries else ""

    def save(self, path: Path) -> None:
        """Persist audit entries to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: list[dict[str, Any]] = [asdict(e) for e in self._entries]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> AuditChain:
        """Load audit entries from a JSON file without recomputing hashes (so tampering is detectable)."""
        chain = cls()
        raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        for item in raw:
            chain._entries.append(AuditEntry(**item))
        return chain

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(self._entries)
