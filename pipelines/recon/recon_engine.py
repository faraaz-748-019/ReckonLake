"""
Three-way UPI reconciliation engine:
    psp_ledger  <->  payer_bank_ledger  <->  switch_ledger

Features:
  - Primary exact matching on `shared_ref`
  - Fallback fuzzy matching on (payer_vpa_token, payee_vpa_token, amount_paise, time_window)
  - Full 7-category break taxonomy:
      MISSING_IN_PSP, MISSING_IN_BANK, MISSING_IN_SWITCH,
      DUPLICATE, AMOUNT_MISMATCH, STATUS_MISMATCH, TIMING_BREAK
  - Deterministic, order-invariant (permutation-invariant), idempotent outputs
  - Precision & recall evaluation against generator ground-truth defect labels
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.observability import RECON_BREAKS_COUNTER, emit_openlineage_event
from pipelines.recon.exception_queue import ExceptionQueue


class ReconBreakCategory(str, Enum):
    MISSING_IN_PSP = "MISSING_IN_PSP"
    MISSING_IN_BANK = "MISSING_IN_BANK"
    MISSING_IN_SWITCH = "MISSING_IN_SWITCH"
    DUPLICATE = "DUPLICATE"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    TIMING_BREAK = "TIMING_BREAK"


SEVERITY_AND_ACTION: dict[ReconBreakCategory, tuple[str, str]] = {
    ReconBreakCategory.MISSING_IN_PSP: ("HIGH", "Query PSP app settlement log and trigger status enquiry"),
    ReconBreakCategory.MISSING_IN_BANK: ("HIGH", "Check CBS debit journal; escalate to payer bank ops"),
    ReconBreakCategory.MISSING_IN_SWITCH: ("HIGH", "Verify NPCI switch RRN log and initiate T+1 dispute"),
    ReconBreakCategory.AMOUNT_MISMATCH: ("HIGH", "Hold settlement and raise chargeback/adjustment ticket"),
    ReconBreakCategory.DUPLICATE: ("MEDIUM", "Deduplicate ledger entry and verify single debit in CBS"),
    ReconBreakCategory.STATUS_MISMATCH: ("MEDIUM", "Re-sync terminal state via NPCI CheckTxn API"),
    ReconBreakCategory.TIMING_BREAK: ("LOW", "Monitor NTP clock drift; auto-clear if within T+1 window"),
}


def _parse_iso(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if ts is None or isinstance(ts, int | float):
        return datetime.fromtimestamp(float(ts or 0), tz=UTC)
    s = str(ts).removeprefix("LATE#")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)


def _safe_int(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _break_id(shared_ref: str, category: ReconBreakCategory) -> str:
    return hashlib.sha256(f"{shared_ref}:{category.value}".encode()).hexdigest()[:16]


def _group_by_ref(events: list[dict[str, Any]], id_field: str) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """
    Order-invariantly index events by shared_ref, detecting duplicate entries
    with distinct event IDs or identical event_ids for the same shared_ref.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        ref = str(ev.get("shared_ref") or "")
        if not ref:
            continue
        grouped.setdefault(ref, []).append(ev)

    canonical: dict[str, dict[str, Any]] = {}
    dup_refs: set[str] = set()
    for ref, lst in grouped.items():
        # Sort canonically by (event_id, canonical_json) so input list permutation never alters output
        sorted_lst = sorted(
            lst,
            key=lambda x: (
                str(x.get(id_field) or x.get("event_id") or ""),
                json.dumps(x, sort_keys=True, default=str),
            ),
        )
        canonical[ref] = sorted_lst[0]
        if len(sorted_lst) > 1:
            dup_refs.add(ref)
    return canonical, dup_refs


def reconcile_three_way(
    psp_events: list[dict[str, Any]],
    bank_events: list[dict[str, Any]],
    switch_events: list[dict[str, Any]],
    recon_date: str,
    timing_tolerance_seconds: float = 300.0,
    fuzzy_window_seconds: float = 300.0,
    reference_now: datetime | None = None,
    quarantined_refs_by_source: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """
    Perform deterministic three-way reconciliation across PSP, Payer Bank, and Switch ledgers.

    Invariants:
      - Permutation-invariant: shuffling input lists produces identical matches & breaks.
      - Conservation: every unique transaction reference is accounted for as either
        matched (clean) or broken (with >= 1 break) or quarantined upstream.
      - Idempotent: running twice produces identical output.
    """
    now = reference_now or datetime.now(UTC)
    q_refs = quarantined_refs_by_source or {}
    q_psp = q_refs.get("psp", set())
    q_bank = q_refs.get("payer_bank", set())
    q_switch = q_refs.get("switch", set())

    psp_map, psp_dups = _group_by_ref(psp_events, "psp_event_id")
    bank_map, bank_dups = _group_by_ref(bank_events, "bank_event_id")
    switch_map, switch_dups = _group_by_ref(switch_events, "switch_event_id")

    all_refs = sorted(set(psp_map) | set(bank_map) | set(switch_map))

    matches: list[dict[str, Any]] = []
    breaks: list[dict[str, Any]] = []
    fuzzy_recovered_refs: set[str] = set()

    # Build O(1) lookup index of unmatched bank events for fast deterministic fuzzy recovery
    unmatched_bank_by_key: dict[tuple[Any, Any, int], list[tuple[str, dict[str, Any]]]] = {}
    for b_ref, b_ev in sorted(bank_map.items()):
        if b_ref in psp_map:
            continue
        b_amt = _safe_int(b_ev.get("amount_paise"))
        if b_amt is None:
            continue
        b_key = (b_ev.get("payer_vpa_token"), b_ev.get("payee_vpa_token"), b_amt)
        unmatched_bank_by_key.setdefault(b_key, []).append((b_ref, b_ev))

    orphan_psp = [r for r in all_refs if r in psp_map and r not in bank_map]
    for ref in orphan_psp:
        p_ev = psp_map[ref]
        p_amt = _safe_int(p_ev.get("amount_paise"))
        if p_amt is None:
            continue
        p_ts = _parse_iso(p_ev.get("timestamp_utc") or p_ev.get("timestamp"))
        p_key = (p_ev.get("payer_vpa_token"), p_ev.get("payee_vpa_token"), p_amt)
        for _b_ref, b_ev in unmatched_bank_by_key.get(p_key, ()):
            b_ts = _parse_iso(b_ev.get("timestamp_utc") or b_ev.get("timestamp"))
            if abs((p_ts - b_ts).total_seconds()) <= fuzzy_window_seconds:
                bank_map[ref] = b_ev
                fuzzy_recovered_refs.add(ref)
                break

    broken_refs: set[str] = set()
    quarantined_upstream_refs: set[str] = set()
    for ref in all_refs:
        p_opt = psp_map.get(ref)
        b_opt = bank_map.get(ref)
        s_opt = switch_map.get(ref)

        # If a missing leg was explicitly quarantined in Bronze/Silver, account for it without
        # false-alarming it as a silent MISSING_IN_* break.
        if (
            (p_opt is None and ref in q_psp)
            or (b_opt is None and ref in q_bank)
            or (s_opt is None and ref in q_switch)
        ):
            quarantined_upstream_refs.add(ref)
            continue

        ref_breaks: list[ReconBreakCategory] = []

        if p_opt is None:
            ref_breaks.append(ReconBreakCategory.MISSING_IN_PSP)
        if b_opt is None:
            ref_breaks.append(ReconBreakCategory.MISSING_IN_BANK)
        if s_opt is None:
            ref_breaks.append(ReconBreakCategory.MISSING_IN_SWITCH)

        if ref in psp_dups or ref in bank_dups or ref in switch_dups:
            ref_breaks.append(ReconBreakCategory.DUPLICATE)

        present = [e for e in (p_opt, b_opt, s_opt) if e is not None]
        if len(present) >= 2:
            amounts = {_safe_int(e.get("amount_paise")) for e in present}
            if len(amounts) > 1 or None in amounts:
                ref_breaks.append(ReconBreakCategory.AMOUNT_MISMATCH)

            states = {str(e.get("state")) for e in present}
            if len(states) > 1:
                ref_breaks.append(ReconBreakCategory.STATUS_MISMATCH)

            timestamps = [_parse_iso(e.get("timestamp_utc") or e.get("timestamp")) for e in present]
            skew_sec = (max(timestamps) - min(timestamps)).total_seconds()
            if skew_sec > timing_tolerance_seconds:
                ref_breaks.append(ReconBreakCategory.TIMING_BREAK)

        if ref_breaks:
            broken_refs.add(ref)
            sample = present[0]
            ev_ts = _parse_iso(sample.get("timestamp_utc") or sample.get("timestamp"))
            age_hours = round(max(0.0, (now - ev_ts).total_seconds() / 3600.0), 2)
            for cat in ref_breaks:
                sev, action = SEVERITY_AND_ACTION[cat]
                RECON_BREAKS_COUNTER.labels(category=cat.value, severity=sev).inc()
                breaks.append(
                    {
                        "break_id": _break_id(ref, cat),
                        "shared_ref": ref,
                        "category": cat.value,
                        "severity": sev,
                        "age_hours": age_hours,
                        "suggested_action": action,
                        "psp_app": str(p_opt.get("psp_id", "UNKNOWN")) if p_opt else "UNKNOWN",
                        "payer_bank_id": str(b_opt.get("bank_id", "UNKNOWN")) if b_opt else "UNKNOWN",
                        "recon_date": recon_date,
                    }
                )
        else:
            assert p_opt is not None and b_opt is not None and s_opt is not None
            matches.append(
                {
                    "shared_ref": ref,
                    "txn_id": str(p_opt["txn_id"]),
                    "amount_paise": _safe_int(p_opt.get("amount_paise")) or 0,
                    "state": str(p_opt["state"]),
                    "psp_app": str(p_opt.get("psp_id", "PSP_01")),
                    "payer_bank_id": str(b_opt.get("bank_id", "AXIS")),
                    "match_type": "FUZZY" if ref in fuzzy_recovered_refs else "EXACT",
                    "recon_date": recon_date,
                }
            )

    # Conservation invariant: every unique reference is in matches OR broken_refs OR quarantined_upstream_refs
    assert len(matches) + len(broken_refs) + len(quarantined_upstream_refs) == len(all_refs)

    # Build summary grouped by (recon_date, psp_app, payer_bank_id)
    summary_map: dict[tuple[str, str], dict[str, int]] = {}
    for m in matches:
        key = (m["psp_app"], m["payer_bank_id"])
        bucket = summary_map.setdefault(key, {"total": 0, "matched": 0, "broken": 0})
        bucket["total"] += 1
        bucket["matched"] += 1
    seen_broken: set[str] = set()
    for b in breaks:
        if b["shared_ref"] in seen_broken:
            continue
        seen_broken.add(b["shared_ref"])
        key = (b["psp_app"], b["payer_bank_id"])
        bucket = summary_map.setdefault(key, {"total": 0, "matched": 0, "broken": 0})
        bucket["total"] += 1
        bucket["broken"] += 1

    summary = [
        {
            "recon_date": recon_date,
            "psp_app": k[0],
            "payer_bank_id": k[1],
            "total_transactions": v["total"],
            "matched_count": v["matched"],
            "break_count": v["broken"],
        }
        for k, v in sorted(summary_map.items())
    ]

    breaks.sort(key=lambda b: (b["shared_ref"], b["category"]))
    matches.sort(key=lambda m: m["shared_ref"])

    return {
        "recon_date": recon_date,
        "total_unique_refs": len(all_refs),
        "matched_count": len(matches),
        "broken_ref_count": len(broken_refs),
        "quarantined_ref_count": len(quarantined_upstream_refs),
        "break_event_count": len(breaks),
        "matches": matches,
        "breaks": breaks,
        "summary": summary,
    }


def _load_quarantined_refs(quarantine_dir: Path | None) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {"psp": set(), "payer_bank": set(), "switch": set()}
    if quarantine_dir is None or not quarantine_dir.exists():
        return refs
    for src in ("psp", "payer_bank", "switch"):
        sdir = quarantine_dir / src
        if sdir.exists():
            for f in sorted(sdir.glob("*.parquet")):
                for r in pq.ParquetFile(f).read().to_pylist():
                    payload_raw = r.get("raw_payload")
                    if payload_raw:
                        try:
                            sref = json.loads(str(payload_raw)).get("shared_ref")
                            if sref:
                                refs[src].add(str(sref))
                        except Exception as exc:
                            import logging

                            logging.debug("Quarantine payload decode skip: %s", exc)
    return refs


def run_reconciliation_to_disk(
    silver_dir: Path,
    recon_dir: Path,
    recon_date: str,
    timing_tolerance_seconds: float = 300.0,
    quarantine_dir: Path | None = None,
) -> dict[str, Any]:
    """Load Silver Parquet tables, reconcile 3 ways, write Delta-style outputs & exception queue."""
    run_id = str(uuid.uuid4())
    emit_openlineage_event(
        job_name="recon_three_way",
        event_type="START",
        inputs=[
            {"namespace": "reconlake", "name": "silver.psp"},
            {"namespace": "reconlake", "name": "silver.payer_bank"},
            {"namespace": "reconlake", "name": "silver.switch"},
        ],
        outputs=[
            {"namespace": "reconlake", "name": "recon.matches"},
            {"namespace": "reconlake", "name": "recon.breaks"},
        ],
        run_id=run_id,
    )

    def _read_silver(src: str) -> list[dict[str, Any]]:
        p = silver_dir / src
        if not p.exists():
            return []
        date_file = p / f"{recon_date}.parquet"
        if date_file.exists():
            return list(pq.ParquetFile(date_file).read().to_pylist())
        files = sorted(p.glob("*.parquet"))
        rows: list[dict[str, Any]] = []
        for f in files:
            for r in pq.ParquetFile(f).read().to_pylist():
                if str(r.get("event_date", "")) == recon_date:
                    rows.append(r)
        return rows

    res = reconcile_three_way(
        psp_events=_read_silver("psp"),
        bank_events=_read_silver("payer_bank"),
        switch_events=_read_silver("switch"),
        recon_date=recon_date,
        timing_tolerance_seconds=timing_tolerance_seconds,
        quarantined_refs_by_source=_load_quarantined_refs(quarantine_dir),
    )

    recon_dir.mkdir(parents=True, exist_ok=True)
    if res["matches"]:
        pq.write_table(pa.Table.from_pylist(res["matches"]), recon_dir / "recon_matches.parquet")
    if res["breaks"]:
        pq.write_table(pa.Table.from_pylist(res["breaks"]), recon_dir / "recon_breaks.parquet")
    if res["summary"]:
        pq.write_table(pa.Table.from_pylist(res["summary"]), recon_dir / "recon_summary.parquet")

    eq = ExceptionQueue()
    for brk in res["breaks"]:
        eq.enqueue(brk)
    eq.save(recon_dir)

    emit_openlineage_event(
        job_name="recon_three_way",
        event_type="COMPLETE",
        inputs=[
            {"namespace": "reconlake", "name": "silver.psp"},
            {"namespace": "reconlake", "name": "silver.payer_bank"},
            {"namespace": "reconlake", "name": "silver.switch"},
        ],
        outputs=[
            {"namespace": "reconlake", "name": "recon.matches"},
            {"namespace": "reconlake", "name": "recon.breaks"},
            {"namespace": "reconlake", "name": "recon.summary"},
        ],
        run_id=run_id,
    )
    return res


def evaluate_against_ground_truth(
    detected_breaks: list[dict[str, Any]],
    defect_labels: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """
    Compute precision and recall per break category against generator ground truth.
    Maps generator BreakCategory names to ReconBreakCategory names.
    """
    cat_map = {
        "MISSING_IN_PSP": "MISSING_IN_PSP",
        "MISSING_IN_PAYER_BANK": "MISSING_IN_BANK",
        "MISSING_IN_SWITCH": "MISSING_IN_SWITCH",
        "AMOUNT_MISMATCH": "AMOUNT_MISMATCH",
        "TIMESTAMP_SKEW": "TIMING_BREAK",
        "DUPLICATE_EVENT": "DUPLICATE",
    }

    gt_by_cat: dict[str, set[str]] = {}
    for lbl in defect_labels:
        raw_cat = str(lbl.get("defect_type", ""))
        mapped = cat_map.get(raw_cat)
        ref = str(lbl.get("shared_ref", ""))
        if mapped and ref:
            gt_by_cat.setdefault(mapped, set()).add(ref)

    det_by_cat: dict[str, set[str]] = {}
    for brk in detected_breaks:
        cat = str(brk.get("category", ""))
        ref = str(brk.get("shared_ref", ""))
        if cat and ref:
            det_by_cat.setdefault(cat, set()).add(ref)

    metrics: dict[str, dict[str, float]] = {}
    for cat in sorted(set(gt_by_cat) | set(det_by_cat)):
        gt = gt_by_cat.get(cat, set())
        det = det_by_cat.get(cat, set())
        tp = len(gt & det)
        precision = tp / len(det) if det else (1.0 if not gt else 0.0)
        recall = tp / len(gt) if gt else 1.0
        metrics[cat] = {
            "ground_truth": float(len(gt)),
            "detected": float(len(det)),
            "true_positives": float(tp),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        }
    return metrics
