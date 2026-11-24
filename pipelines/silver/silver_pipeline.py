"""
Silver layer transformation, deduplication, DQ gating, and idempotent upsert.

Invariants enforced (and property-tested with Hypothesis):
  rows_in == rows_out + rows_quarantined + rows_deduplicated
  Re-running the exact same batch produces identical Silver state (idempotency).
  Circuit breaker halts Gold promotion and keeps batch in silver_pending if DQ < threshold.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from contracts.validator import load_contract, validate_event
from pipelines.observability import (
    DQ_SCORE_GAUGE,
    PROCESSING_LAG,
    ROWS_IN,
    ROWS_OUT,
    ROWS_QUARANTINED,
    emit_openlineage_event,
)
from quality.dq_score import DQCircuitBreaker, DQCircuitBreakerError, DQScore
from quality.great_expectations.expectations_suite import EVENT_ID_KEY, run_silver_expectations

ALLOWED_LATE_HOURS = 72


def _parse_ts_utc(val: Any) -> tuple[datetime | None, bool]:
    """Parse ISO timestamp or LATE# marker to UTC datetime. Returns (dt, is_late_marked)."""
    if val is None:
        return None, False
    if isinstance(val, datetime):
        dt = val if val.tzinfo else val.replace(tzinfo=UTC)
        return dt.astimezone(UTC), False
    if isinstance(val, str):
        is_late = val.startswith("LATE#")
        raw = val.removeprefix("LATE#")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC), is_late
        except ValueError:
            return None, is_late
    return None, False


def process_silver_records(
    records: list[dict[str, Any]],
    source: str,
    batch_date: str,
    silver_dir: Path,
    quarantine_dir: Path,
    dq_threshold: float | None = None,
    reference_now: datetime | None = None,
    enforce_circuit_breaker: bool = True,
) -> dict[str, Any]:
    """
    Cleanse, deduplicate, validate, score, and idempotently upsert *records* for *source*.

    Guarantees conservation:
        rows_in == rows_out + rows_quarantined + rows_deduplicated
    """
    contract = load_contract(source)
    threshold = dq_threshold if dq_threshold is not None else float(contract.get("dq_threshold", 0.90))
    id_col = EVENT_ID_KEY[source]
    now = reference_now or datetime.now(UTC)
    sla_minutes = int(contract.get("freshness_sla_minutes", 10))

    run_id = str(uuid.uuid4())
    emit_openlineage_event(
        job_name=f"silver_pipeline_{source}",
        event_type="START",
        inputs=[{"namespace": "reconlake", "name": f"bronze.{source}"}],
        outputs=[{"namespace": "reconlake", "name": f"silver.{source}"}],
        run_id=run_id,
    )

    rows_in = len(records)
    ROWS_IN.labels(layer="silver", source=source).inc(rows_in)

    valid_candidates: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    timely_count = 0
    null_key_count = 0

    for rec in records:
        row = dict(rec)
        # Parse LATE# timestamps if present, recording lateness
        raw_ts = row.get("timestamp") or row.get("timestamp_utc")
        parsed_ts, is_late = _parse_ts_utc(raw_ts)

        # Strip bronze-only metadata before contract check if validating raw-shaped rows
        meta_keys = ("source", "batch_id", "ingested_at", "contract_version", "raw_payload_sha256", "event_date")
        contract_view = {k: v for k, v in row.items() if k not in meta_keys and k != "timestamp_utc"}
        if "timestamp" not in contract_view and "timestamp_utc" in row:
            contract_view["timestamp"] = row["timestamp_utc"]

        is_valid, reasons = validate_event(contract_view, contract)
        if not is_valid or parsed_ts is None:
            if any(r.startswith("NULL_KEY") for r in reasons):
                null_key_count += 1
            reason_code = reasons[0].split(":")[0] if reasons else "INVALID_TIMESTAMP"
            raw_hash = row.get("raw_payload_sha256") or hashlib.sha256(
                json.dumps(row, sort_keys=True, default=str).encode()
            ).hexdigest()
            quarantine_rows.append(
                {
                    "source": source,
                    "event_id": str(row.get(id_col) or ""),
                    "raw_payload_sha256": raw_hash,
                    "rule_name": "silver_contract_gate",
                    "reason_code": reason_code,
                    "reason_details": json.dumps(reasons),
                    "batch_date": batch_date,
                }
            )
            ROWS_QUARANTINED.labels(layer="silver", source=source, reason_code=reason_code).inc()
            continue

        # Watermark & timeliness check
        if reference_now is not None:
            lag_seconds = max(0.0, (now - parsed_ts).total_seconds())
            is_timely = lag_seconds <= sla_minutes * 60
        else:
            # In batch mode, check whether event was backdated/late-marked or outside batch_date
            is_timely = (not is_late) and (parsed_ts.strftime("%Y-%m-%d") == batch_date)
            lag_seconds = 0.0 if is_timely else float(sla_minutes * 60 + 1)
        PROCESSING_LAG.labels(layer="silver", source=source).observe(lag_seconds)
        if is_timely:
            timely_count += 1

        normalised = dict(contract_view)
        normalised["source"] = source
        normalised["event_id"] = str(normalised[id_col])
        normalised["amount_paise"] = int(normalised["amount_paise"])
        normalised["timestamp_utc"] = parsed_ts.isoformat()
        normalised["event_date"] = parsed_ts.strftime("%Y-%m-%d")
        normalised["ingested_at"] = str(row.get("ingested_at") or now.isoformat())
        normalised["raw_payload_sha256"] = str(
            row.get("raw_payload_sha256")
            or hashlib.sha256(json.dumps(contract_view, sort_keys=True, default=str).encode()).hexdigest()
        )
        valid_candidates.append(normalised)

    # Deduplicate by (source, event_id), keeping latest ingested_at
    dedup_map: dict[tuple[str, str], dict[str, Any]] = {}
    rows_deduplicated = 0
    for cand in valid_candidates:
        key = (cand["source"], cand["event_id"])
        if key in dedup_map:
            rows_deduplicated += 1
            if cand["ingested_at"] >= dedup_map[key]["ingested_at"]:
                dedup_map[key] = cand
        else:
            dedup_map[key] = cand

    clean_rows = list(dedup_map.values())
    rows_out = len(clean_rows)
    rows_quarantined = len(quarantine_rows)

    # Conservation invariant
    assert rows_in == rows_out + rows_quarantined + rows_deduplicated

    # Great Expectations suite on clean rows
    gx_report = run_silver_expectations(clean_rows, source)

    # Compute 5-dimension Data Quality Score
    denom = max(1, rows_in)
    completeness = max(0.0, min(1.0, (rows_in - null_key_count) / denom))
    validity = max(0.0, min(1.0, (rows_out + rows_deduplicated) / denom))
    uniqueness = max(0.0, min(1.0, 1.0 - (rows_deduplicated / denom)))
    timeliness = max(0.0, min(1.0, timely_count / max(1, rows_out))) if rows_out else 1.0
    consistency = (
        1.0
        if gx_report["success"]
        else max(0.0, gx_report["passed_expectations"] / max(1, len(gx_report["results"])))
    )

    dq = DQScore(
        source=source,
        batch_date=batch_date,
        completeness=completeness,
        validity=validity,
        uniqueness=uniqueness,
        timeliness=timeliness,
        consistency=consistency,
    )
    DQ_SCORE_GAUGE.labels(source=source).set(dq.overall)

    # Write quarantine regardless of circuit breaker
    if quarantine_rows:
        q_dir = quarantine_dir / "silver" / source
        q_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(quarantine_rows), q_dir / f"{batch_date}.parquet")

    # Circuit breaker evaluation
    gate_passed = True
    target_subdir = source
    try:
        DQCircuitBreaker(threshold=threshold).evaluate(dq)
    except DQCircuitBreakerError:
        gate_passed = False
        if enforce_circuit_breaker:
            target_subdir = f"silver_pending/{source}"
            # Write to silver_pending, record DQ score, emit lineage, and re-raise
            _upsert_silver_parquet(silver_dir / target_subdir / f"{batch_date}.parquet", clean_rows)
            _write_dq_score(silver_dir / "_dq_scores", dq, gate_passed)
            emit_openlineage_event(
                job_name=f"silver_pipeline_{source}",
                event_type="FAIL",
                inputs=[{"namespace": "reconlake", "name": f"bronze.{source}"}],
                outputs=[{"namespace": "reconlake", "name": f"silver_pending.{source}"}],
                run_id=run_id,
            )
            raise

    # Idempotent upsert into Silver
    _upsert_silver_parquet(silver_dir / target_subdir / f"{batch_date}.parquet", clean_rows)
    _write_dq_score(silver_dir / "_dq_scores", dq, gate_passed)
    ROWS_OUT.labels(layer="silver", source=source).inc(rows_out)

    emit_openlineage_event(
        job_name=f"silver_pipeline_{source}",
        event_type="COMPLETE",
        inputs=[{"namespace": "reconlake", "name": f"bronze.{source}"}],
        outputs=[{"namespace": "reconlake", "name": f"silver.{source}"}],
        run_id=run_id,
    )

    return {
        "source": source,
        "batch_date": batch_date,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_quarantined": rows_quarantined,
        "rows_deduplicated": rows_deduplicated,
        "dq_score": dq.to_dict(),
        "gate_passed": gate_passed,
        "gx_success": gx_report["success"],
    }


def _upsert_silver_parquet(target_file: Path, new_rows: list[dict[str, Any]]) -> None:
    """Idempotent Delta-MERGE-equivalent upsert by (source, event_id) into Parquet."""
    target_file.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    if target_file.exists():
        existing = pq.ParquetFile(target_file).read().to_pylist()
        for r in existing:
            merged[(str(r["source"]), str(r["event_id"]))] = r
    for r in new_rows:
        merged[(str(r["source"]), str(r["event_id"]))] = r
    if merged:
        rows = list(merged.values())
        norm = [
            {k: (None if v is None else int(v) if k == "amount_paise" else str(v)) for k, v in r.items()}
            for r in rows
        ]
        pq.write_table(pa.Table.from_pylist(norm), target_file)


def _write_dq_score(dq_dir: Path, dq: DQScore, gate_passed: bool) -> None:
    dq_dir.mkdir(parents=True, exist_ok=True)
    rec = dq.to_dict()
    rec["gate_passed"] = gate_passed
    out = dq_dir / f"{dq.source}_{dq.batch_date}.json"
    out.write_text(json.dumps(rec, indent=2), encoding="utf-8")
