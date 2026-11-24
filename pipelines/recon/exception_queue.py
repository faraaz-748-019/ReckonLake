"""
Exception Queue workflow for reconciliation breaks.

Lifecycle:
    OPEN -> INVESTIGATING -> RESOLVED
Every transition appends an immutable record to `exception_history` and logs
an EXCEPTION_QUEUE_CHANGE entry to the hash-chained AuditChain.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from security.audit_chain import AuditChain


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"


VALID_STATUS_TRANSITIONS: dict[ExceptionStatus, frozenset[ExceptionStatus]] = {
    ExceptionStatus.OPEN: frozenset({ExceptionStatus.INVESTIGATING, ExceptionStatus.RESOLVED}),
    ExceptionStatus.INVESTIGATING: frozenset({ExceptionStatus.RESOLVED, ExceptionStatus.OPEN}),
    ExceptionStatus.RESOLVED: frozenset(),
}


@dataclass
class ExceptionItem:
    break_id: str
    shared_ref: str
    category: str
    severity: str
    suggested_action: str
    status: ExceptionStatus = ExceptionStatus.OPEN
    assignee: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ExceptionHistoryRecord:
    history_id: str
    break_id: str
    from_status: str | None
    to_status: str
    actor: str
    note: str
    changed_at: str


class ExceptionQueue:
    """In-memory / JSON-persisted Exception Queue with immutable transition history."""

    def __init__(self, audit_chain: AuditChain | None = None) -> None:
        self.items: dict[str, ExceptionItem] = {}
        self.history: list[ExceptionHistoryRecord] = []
        self.audit_chain = audit_chain or AuditChain()

    def enqueue(self, brk: dict[str, Any], actor: str = "recon_engine") -> ExceptionItem:
        """Idempotently enqueue a break into the exception queue."""
        break_id = str(brk["break_id"])
        if break_id in self.items:
            return self.items[break_id]

        item = ExceptionItem(
            break_id=break_id,
            shared_ref=str(brk["shared_ref"]),
            category=str(brk["category"]),
            severity=str(brk["severity"]),
            suggested_action=str(brk["suggested_action"]),
            status=ExceptionStatus.OPEN,
        )
        self.items[break_id] = item
        self.history.append(
            ExceptionHistoryRecord(
                history_id=str(uuid.uuid4()),
                break_id=break_id,
                from_status=None,
                to_status=ExceptionStatus.OPEN.value,
                actor=actor,
                note="Auto-enqueued from reconciliation break",
                changed_at=datetime.now(UTC).isoformat(),
            )
        )
        self.audit_chain.append(
            event_type="EXCEPTION_QUEUE_CHANGE",
            actor=actor,
            resource=f"break:{break_id}",
            details={"action": "ENQUEUE", "category": item.category, "status": item.status.value},
        )
        return item

    def transition(
        self,
        break_id: str,
        to_status: ExceptionStatus,
        actor: str,
        note: str = "",
        assignee: str | None = None,
    ) -> ExceptionItem:
        """Transition an exception item to a valid next status, recording immutable history."""
        if break_id not in self.items:
            raise KeyError(f"Unknown break_id: {break_id}")
        item = self.items[break_id]
        if to_status not in VALID_STATUS_TRANSITIONS[item.status]:
            raise ValueError(f"Illegal transition {item.status.value} -> {to_status.value}")

        old_status = item.status
        item.status = to_status
        if assignee is not None:
            item.assignee = assignee

        self.history.append(
            ExceptionHistoryRecord(
                history_id=str(uuid.uuid4()),
                break_id=break_id,
                from_status=old_status.value,
                to_status=to_status.value,
                actor=actor,
                note=note,
                changed_at=datetime.now(UTC).isoformat(),
            )
        )
        self.audit_chain.append(
            event_type="EXCEPTION_QUEUE_CHANGE",
            actor=actor,
            resource=f"break:{break_id}",
            details={"from": old_status.value, "to": to_status.value, "note": note},
        )
        return item

    def save(self, queue_dir: Path) -> None:
        queue_dir.mkdir(parents=True, exist_ok=True)
        items_data = [
            {**asdict(v), "status": v.status.value}
            for v in sorted(self.items.values(), key=lambda x: x.break_id)
        ]
        (queue_dir / "exception_queue.json").write_text(json.dumps(items_data, indent=2), encoding="utf-8")
        (queue_dir / "exception_history.json").write_text(
            json.dumps([asdict(h) for h in self.history], indent=2), encoding="utf-8"
        )
