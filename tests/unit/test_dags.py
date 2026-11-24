"""DAG import, syntax, and out-of-order backfill equivalence tests."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from dags.common import run_day_pipeline
from generator.producer import UPIGenerator


@pytest.mark.unit
def test_all_dags_parse_and_import_cleanly() -> None:
    dag_files = [
        "ingest_batch",
        "silver_pipeline",
        "recon_daily",
        "gold_load_and_dbt",
        "dq_report",
        "backfill",
    ]
    for name in dag_files:
        path = Path("dags") / f"{name}.py"
        ast.parse(path.read_text(encoding="utf-8"))
        mod = importlib.import_module(f"dags.{name}")
        assert mod is not None


@pytest.mark.unit
def test_out_of_order_backfill_equals_straight_through(tmp_path: Path) -> None:
    gen = UPIGenerator(seed=101, count=60, batch_size=20, defect_profile="low", fraud_profile="none")
    raw_dir = tmp_path / "raw"
    gen.write_files(raw_dir, file_format="jsonl")

    dates = ["2026-11-01", "2026-11-02", "2026-11-03"]
    straight_dir = tmp_path / "straight"
    backfill_dir = tmp_path / "backfill"

    straight_res = {d: run_day_pipeline(d, raw_dir=raw_dir, lake_dir=straight_dir) for d in dates}
    # Run in reverse / scrambled order
    backfill_res = {
        d: run_day_pipeline(d, raw_dir=raw_dir, lake_dir=backfill_dir)
        for d in ["2026-11-03", "2026-11-01", "2026-11-02"]
    }

    import pyarrow.parquet as pq

    for d in dates:
        assert straight_res[d]["recon_matched"] > 0
        assert straight_res[d]["recon_matched"] == backfill_res[d]["recon_matched"]
        assert straight_res[d]["recon_breaks"] == backfill_res[d]["recon_breaks"]

    straight_gold = pq.ParquetFile(straight_dir / "gold" / "daily_settlement_kpis.parquet").read().to_pylist()
    backfill_gold = pq.ParquetFile(backfill_dir / "gold" / "daily_settlement_kpis.parquet").read().to_pylist()
    assert straight_gold == backfill_gold
