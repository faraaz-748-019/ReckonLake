"""Unit tests for Silver cleansing, deduplication, quarantine, DQ score, and circuit breaker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from generator.producer import UPIGenerator
from pipelines.silver.silver_pipeline import process_silver_records
from quality.dq_score import DQCircuitBreakerError


@pytest.mark.unit
def test_silver_dedup_quarantine_and_idempotency(tmp_path: Path) -> None:
    gen = UPIGenerator(seed=42, count=100, defect_profile="none", fraud_profile="none")
    psp_ev, _, _, _, _ = next(gen.generate())

    # Inject 5 duplicates and 3 null-key rows
    with_defects = list(psp_ev)
    for i in range(5):
        with_defects.append(dict(psp_ev[i]))
    for i in range(3):
        bad = dict(psp_ev[10 + i])
        bad["amount_paise"] = None
        with_defects.append(bad)

    silver_dir = tmp_path / "silver"
    q_dir = tmp_path / "quarantine"
    now = datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC)

    res1 = process_silver_records(
        with_defects,
        source="psp",
        batch_date="2026-11-01",
        silver_dir=silver_dir,
        quarantine_dir=q_dir,
        dq_threshold=0.50,
        reference_now=now,
    )
    assert res1["rows_in"] == 108
    assert res1["rows_deduplicated"] == 5
    assert res1["rows_quarantined"] == 3
    assert res1["rows_out"] == 100
    assert res1["rows_in"] == res1["rows_out"] + res1["rows_quarantined"] + res1["rows_deduplicated"]

    # Idempotency: running exact same batch again changes nothing
    import pyarrow.parquet as pq

    before = pq.read_table(silver_dir / "psp" / "2026-11-01.parquet").to_pylist()
    process_silver_records(
        with_defects,
        source="psp",
        batch_date="2026-11-01",
        silver_dir=silver_dir,
        quarantine_dir=q_dir,
        dq_threshold=0.50,
        reference_now=now,
    )
    after = pq.read_table(silver_dir / "psp" / "2026-11-01.parquet").to_pylist()
    assert len(before) == len(after) == 100


@pytest.mark.unit
def test_silver_circuit_breaker_halts_gold(tmp_path: Path) -> None:
    gen = UPIGenerator(seed=5, count=20, defect_profile="high", fraud_profile="none")
    psp_ev, _, _, _, _ = next(gen.generate())

    # Force a strict 0.999 threshold on high-defect data -> triggers circuit breaker
    with pytest.raises(DQCircuitBreakerError):
        process_silver_records(
            psp_ev,
            source="psp",
            batch_date="2026-11-01",
            silver_dir=tmp_path / "silver",
            quarantine_dir=tmp_path / "quarantine",
            dq_threshold=0.999,
            enforce_circuit_breaker=True,
        )
    # Batch must remain in silver_pending, not promoted to silver/psp
    assert (tmp_path / "silver" / "silver_pending" / "psp" / "2026-11-01.parquet").exists()
    assert not (tmp_path / "silver" / "psp" / "2026-11-01.parquet").exists()
