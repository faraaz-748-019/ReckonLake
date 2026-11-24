"""
Data-quality defect injector for the ReconLake UPI generator.

Each ``inject_*`` function:
  - Accepts a list of event dicts (PSP / payer-bank / switch) and a rate ∈ [0, 1].
  - Randomly selects ``ceil(len(events) * rate)`` events to corrupt.
  - Returns (modified_events, [DefectLabel, ...]) so callers can build ground-truth.

The events are plain ``dict`` objects (serialised from Pydantic models) so we
can freely add, remove and rename keys without touching the model classes.
"""

from __future__ import annotations

import copy
import math
import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from generator.models import BreakCategory, DefectLabel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_indices(n: int, rate: float, rng: random.Random) -> list[int]:
    """Return a list of indices to corrupt, respecting *rate*."""
    k = max(0, min(n, math.ceil(n * rate)))
    if k == 0 or n == 0:
        return []
    return rng.sample(range(n), k=k)


def _event_id(event: dict[str, Any]) -> str:
    """Return whichever ID field is present on this event dict."""
    for key in ("psp_event_id", "bank_event_id", "switch_event_id"):
        if key in event:
            return str(event[key])
    return str(event.get("id", str(uuid.uuid4())))


def _ledger(event: dict[str, Any]) -> str:
    if "psp_event_id" in event:
        return "psp"
    if "bank_event_id" in event:
        return "payer_bank"
    return "switch"


# ---------------------------------------------------------------------------
# Defect injectors
# ---------------------------------------------------------------------------


def inject_duplicates(
    events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], list[DefectLabel]]:
    """
    Duplicate rows: insert an identical copy of each selected event
    (same event_id, same payload) immediately after the original.
    Models an at-least-once delivery bug in a Kafka consumer.
    """
    labels: list[DefectLabel] = []
    dup_set = set(_sample_indices(len(events), rate, rng))
    out: list[dict[str, Any]] = []
    for idx, orig in enumerate(events):
        out.append(orig)
        if idx in dup_set:
            dup = copy.deepcopy(orig)
            out.append(dup)
            labels.append(
                DefectLabel(
                    event_id=_event_id(orig),
                    shared_ref=orig.get("shared_ref", ""),
                    ledger=_ledger(orig),
                    defect_type=BreakCategory.DUPLICATE_EVENT,
                    details={"duplicate_index": len(out) - 1},
                )
            )
    return out, labels


def _shift_timestamp(orig_ts: Any, delta: timedelta) -> Any:
    """Shift a datetime or ISO-8601 timestamp string by *delta*."""
    if isinstance(orig_ts, datetime) or hasattr(orig_ts, "isoformat"):
        return orig_ts + delta
    if isinstance(orig_ts, str):
        try:
            dt = datetime.fromisoformat(orig_ts.replace("Z", "+00:00"))
            return (dt + delta).isoformat()
        except ValueError:
            return f"LATE#{orig_ts}"
    return orig_ts


def inject_late_events(
    events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
    *,
    min_hours: int = 1,
    max_hours: int = 48,
) -> tuple[list[dict[str, Any]], list[DefectLabel]]:
    """
    Backdate timestamps by 1-48 hours to simulate late-arriving records
    (e.g. a CBS that batches uploads overnight).
    """
    labels: list[DefectLabel] = []
    for idx in _sample_indices(len(events), rate, rng):
        ev = events[idx]
        hours_back = rng.uniform(min_hours, max_hours)
        ev["timestamp"] = _shift_timestamp(ev.get("timestamp", ""), timedelta(hours=-hours_back))
        labels.append(
            DefectLabel(
                event_id=_event_id(ev),
                shared_ref=ev.get("shared_ref", ""),
                ledger=_ledger(ev),
                defect_type=BreakCategory.LATE_ARRIVAL,
                details={"hours_backdated": round(hours_back, 2)},
            )
        )
    return events, labels


def inject_null_keys(
    events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
    *,
    nullable_fields: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[DefectLabel]]:
    """
    Null out a critical field (amount_paise, payer_vpa_token, payee_vpa_token,
    shared_ref) to simulate incomplete CBS exports or truncation bugs.
    """
    if nullable_fields is None:
        nullable_fields = ["amount_paise", "payer_vpa_token", "payee_vpa_token", "shared_ref"]
    labels: list[DefectLabel] = []
    for idx in _sample_indices(len(events), rate, rng):
        ev = events[idx]
        field = rng.choice([f for f in nullable_fields if f in ev] or nullable_fields)
        ev[field] = None
        labels.append(
            DefectLabel(
                event_id=_event_id(ev),
                shared_ref=ev.get("shared_ref") or "",
                ledger=_ledger(ev),
                defect_type=BreakCategory.NULL_KEY,
                details={"nulled_field": field},
            )
        )
    return events, labels


def inject_wrong_types(
    events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], list[DefectLabel]]:
    """
    Introduce type mismatches: e.g. amount as a string instead of int,
    or timestamp as an integer epoch instead of ISO string.
    Simulates schema evolution bugs or misconfigured serialisers.
    """
    labels: list[DefectLabel] = []
    mutations = {
        "amount_paise": lambda v: str(v) if v is not None else "NULL",
        "timestamp": lambda v: int(v.timestamp()) if hasattr(v, "timestamp") else 0,
        "state": lambda v: 42,  # integer where string expected
        "type": lambda v: [v],  # list where string expected
    }
    for idx in _sample_indices(len(events), rate, rng):
        ev = events[idx]
        field = rng.choice(list(mutations))
        orig = ev.get(field)
        ev[field] = mutations[field](orig)
        labels.append(
            DefectLabel(
                event_id=_event_id(ev),
                shared_ref=ev.get("shared_ref", ""),
                ledger=_ledger(ev),
                defect_type=BreakCategory.WRONG_TYPE,
                details={"field": field, "original_type": type(orig).__name__},
            )
        )
    return events, labels


def inject_schema_drift(
    events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], list[DefectLabel]]:
    """
    Add unknown fields or rename existing ones to simulate schema drift:
    a producer that added a new column, or a field that was renamed
    during a migration.
    """
    labels: list[DefectLabel] = []
    rename_candidates = ["state", "type", "amount_paise"]

    for idx in _sample_indices(len(events), rate, rng):
        ev = events[idx]
        action = rng.choice(["add_field", "rename_field"])
        if action == "add_field":
            new_key = f"_drift_{rng.getrandbits(24):06x}"
            ev[new_key] = rng.random()
            details = {"action": "add_field", "field": new_key}
        else:
            old_key = rng.choice(rename_candidates)
            if old_key in ev:
                new_key = f"{old_key}_v2"
                ev[new_key] = ev.pop(old_key)
                details = {"action": "rename_field", "from": old_key, "to": new_key}
            else:
                details = {"action": "rename_field", "skipped": "field_not_found"}
        labels.append(
            DefectLabel(
                event_id=_event_id(ev),
                shared_ref=ev.get("shared_ref", ""),
                ledger=_ledger(ev),
                defect_type=BreakCategory.SCHEMA_DRIFT,
                details=details,
            )
        )
    return events, labels


def inject_clock_skew(
    events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
    *,
    min_skew_seconds: int = 300,
    max_skew_seconds: int = 3600,
) -> tuple[list[dict[str, Any]], list[DefectLabel]]:
    """
    Shift timestamps forward or backward by 5 min - 1 hour to simulate
    NTP drift between the PSP and bank CBS clocks.  When the same
    ``shared_ref`` has cross-ledger skew > 5 min the recon engine should
    raise a TIMESTAMP_SKEW break.
    """
    labels: list[DefectLabel] = []
    for idx in _sample_indices(len(events), rate, rng):
        ev = events[idx]
        skew_s = rng.uniform(min_skew_seconds, max_skew_seconds)
        direction = rng.choice([-1, 1])
        ev["timestamp"] = _shift_timestamp(ev.get("timestamp"), timedelta(seconds=direction * skew_s))
        labels.append(
            DefectLabel(
                event_id=_event_id(ev),
                shared_ref=ev.get("shared_ref", ""),
                ledger=_ledger(ev),
                defect_type=BreakCategory.TIMESTAMP_SKEW,
                details={"skew_seconds": round(direction * skew_s, 1)},
            )
        )
    return events, labels


def inject_missing_ledger_entry(
    psp_events: list[dict[str, Any]],
    payer_bank_events: list[dict[str, Any]],
    switch_events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[DefectLabel],
]:
    """
    Remove one ledger's record for a transaction entirely, leaving the
    other two present.  Simulates a silent CBS drop or Kafka topic lag
    that caused a consumer to never write the record.
    """
    labels: list[DefectLabel] = []
    # Build index by shared_ref across all three ledgers
    psp_by_ref = {e["shared_ref"]: i for i, e in enumerate(psp_events) if "shared_ref" in e}
    payer_by_ref = {e["shared_ref"]: i for i, e in enumerate(payer_bank_events) if "shared_ref" in e}
    switch_by_ref = {e["shared_ref"]: i for i, e in enumerate(switch_events) if "shared_ref" in e}

    # Only refs present in ALL three ledgers can have one removed
    full_refs = list(set(psp_by_ref) & set(payer_by_ref) & set(switch_by_ref))
    k = max(0, min(len(full_refs), math.ceil(len(full_refs) * rate)))
    if k == 0:
        return psp_events, payer_bank_events, switch_events, labels

    chosen_refs = rng.sample(full_refs, k=k)
    remove_psp_idx: set[int] = set()
    remove_payer_idx: set[int] = set()
    remove_switch_idx: set[int] = set()

    for ref in chosen_refs:
        ledger = rng.choice(["psp", "payer_bank", "switch"])
        if ledger == "psp":
            remove_psp_idx.add(psp_by_ref[ref])
            break_cat = BreakCategory.MISSING_IN_PSP
            ev_id = _event_id(psp_events[psp_by_ref[ref]])
        elif ledger == "payer_bank":
            remove_payer_idx.add(payer_by_ref[ref])
            break_cat = BreakCategory.MISSING_IN_PAYER_BANK
            ev_id = _event_id(payer_bank_events[payer_by_ref[ref]])
        else:
            remove_switch_idx.add(switch_by_ref[ref])
            break_cat = BreakCategory.MISSING_IN_SWITCH
            ev_id = _event_id(switch_events[switch_by_ref[ref]])
        labels.append(
            DefectLabel(
                event_id=ev_id,
                shared_ref=ref,
                ledger=ledger,
                defect_type=break_cat,
                details={"removed_ledger": ledger},
            )
        )

    psp_events = [e for i, e in enumerate(psp_events) if i not in remove_psp_idx]
    payer_bank_events = [e for i, e in enumerate(payer_bank_events) if i not in remove_payer_idx]
    switch_events = [e for i, e in enumerate(switch_events) if i not in remove_switch_idx]

    return psp_events, payer_bank_events, switch_events, labels


def inject_amount_mismatch(
    psp_events: list[dict[str, Any]],
    payer_bank_events: list[dict[str, Any]],
    switch_events: list[dict[str, Any]],
    rate: float,
    rng: random.Random,
    *,
    max_delta_paise: int = 100_00,  # up to ₹100 mismatch
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[DefectLabel],
]:
    """
    Alter the amount_paise in one ledger's record to differ from the
    other two, simulating a rounding bug or FX conversion artefact.
    """
    labels: list[DefectLabel] = []
    psp_by_ref = {e["shared_ref"]: i for i, e in enumerate(psp_events) if "shared_ref" in e}
    payer_by_ref = {e["shared_ref"]: i for i, e in enumerate(payer_bank_events) if "shared_ref" in e}
    switch_by_ref = {e["shared_ref"]: i for i, e in enumerate(switch_events) if "shared_ref" in e}
    full_refs = list(set(psp_by_ref) & set(payer_by_ref) & set(switch_by_ref))

    k = max(0, min(len(full_refs), math.ceil(len(full_refs) * rate)))
    if k == 0:
        return psp_events, payer_bank_events, switch_events, labels

    chosen_refs = rng.sample(full_refs, k=k)
    ledger_map = {
        "psp": (psp_events, psp_by_ref),
        "payer_bank": (payer_bank_events, payer_by_ref),
        "switch": (switch_events, switch_by_ref),
    }

    for ref in chosen_refs:
        ledger = rng.choice(["psp", "payer_bank", "switch"])
        lst, idx_map = ledger_map[ledger]
        ev = lst[idx_map[ref]]
        orig_amount = ev.get("amount_paise", 0) or 0
        delta = rng.randint(1, max_delta_paise)
        ev["amount_paise"] = orig_amount + rng.choice([-1, 1]) * delta
        labels.append(
            DefectLabel(
                event_id=_event_id(ev),
                shared_ref=ref,
                ledger=ledger,
                defect_type=BreakCategory.AMOUNT_MISMATCH,
                details={"original_amount_paise": orig_amount, "delta_paise": delta},
            )
        )

    return psp_events, payer_bank_events, switch_events, labels
