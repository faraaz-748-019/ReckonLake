"""Chaos and recovery tests: mid-run crash recovery, zero duplicates, zero data loss."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from generator.producer import UPIGenerator
from pipelines.bronze.streaming_ingest import ingest_records_to_bronze


@pytest.mark.chaos
def test_bronze_mid_run_crash_and_restart_zero_loss_zero_dups(tmp_path: Path) -> None:
    gen = UPIGenerator(seed=77, count=200, defect_profile="none", fraud_profile="none")
    psp, _, _, _, _ = next(gen.generate())

    bronze_dir = tmp_path / "bronze"
    q_dir = tmp_path / "quarantine"
    ckpt = bronze_dir / "_checkpoints" / "psp.ckpt.json"

    # Simulate container/job crash mid-run after 85 events
    with pytest.raises(RuntimeError, match="Simulated mid-run crash"):
        ingest_records_to_bronze(
            records=psp,
            source="psp",
            bronze_dir=bronze_dir,
            quarantine_dir=q_dir,
            checkpoint_path=ckpt,
            fail_after_n=85,
        )

    # Restart job with same checkpoint -> processes remaining 115 events cleanly
    res2 = ingest_records_to_bronze(
        records=psp,
        source="psp",
        bronze_dir=bronze_dir,
        quarantine_dir=q_dir,
        checkpoint_path=ckpt,
    )
    assert res2["bronze_written"] == 115

    # Verify total rows in Bronze == 200 and unique event IDs == 200 (zero loss, zero duplicates)
    all_rows = []
    for f in sorted((bronze_dir / "psp").rglob("*.parquet")):
        all_rows.extend(pq.ParquetFile(f).read().to_pylist())
    assert len(all_rows) == 200
    assert len({r["psp_event_id"] for r in all_rows}) == 200
