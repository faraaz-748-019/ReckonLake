"""
Shared Airflow DAG configuration:
  - Alertmanager webhook failure callback
  - Data-aware Airflow Datasets (Bronze -> Silver DQ Gate -> Recon -> Gold)
  - Idempotent task runner helpers
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

try:
    from airflow.datasets import Dataset
except ImportError:  # pragma: no cover - allows offline unit testing on Windows without Airflow installed
    class Dataset:  # type: ignore[no-redef]
        def __init__(self, uri: str) -> None:
            self.uri = uri


DATASET_BRONZE_READY = Dataset("reconlake://bronze/all_ledgers")
DATASET_SILVER_DQ_PASSED = Dataset("reconlake://silver/dq_gate_passed")
DATASET_RECON_READY = Dataset("reconlake://recon/completed")
DATASET_GOLD_READY = Dataset("reconlake://gold/marts_refreshed")


def alertmanager_failure_callback(context: dict[str, Any]) -> None:
    """Send DAG/task failure alert to Prometheus Alertmanager."""
    url = os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093/api/v2/alerts")
    ti = context.get("task_instance")
    dag_id = getattr(ti, "dag_id", "unknown")
    task_id = getattr(ti, "task_id", "unknown")
    payload = [
        {
            "labels": {
                "alertname": "FailedAirflowDAG",
                "severity": "critical",
                "dag_id": str(dag_id),
                "task_id": str(task_id),
            },
            "annotations": {
                "summary": f"Airflow task {dag_id}.{task_id} failed",
                "runbook": "docs/runbooks/failed-dag.md",
            },
        }
    ]
    try:
        httpx.post(url, json=payload, timeout=2.0)
    except Exception as exc:
        logging.warning("Alertmanager notification skipped/failed: %s", exc)


DEFAULT_ARGS: dict[str, Any] = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=1),
    "sla": timedelta(minutes=30),
    "on_failure_callback": alertmanager_failure_callback,
}


def run_day_pipeline(
    ds: str,
    raw_dir: Path = Path("data/raw"),
    lake_dir: Path = Path("data"),
) -> dict[str, Any]:
    """
    Execute an idempotent single-day pipeline slice (Bronze -> Silver -> Recon -> Gold).
    Used by Airflow tasks and verified in out-of-order backfill tests.
    """
    from pipelines.bronze.batch_ingest import run_batch_ingest
    from pipelines.gold.gold_load import load_gold_local
    from pipelines.recon.recon_engine import run_reconciliation_to_disk
    from pipelines.silver.silver_pipeline import process_silver_records

    bronze_dir = lake_dir / "bronze"
    silver_dir = lake_dir / "silver"
    quarantine_dir = lake_dir / "quarantine"
    recon_dir = lake_dir / "recon" / ds
    gold_dir = lake_dir / "gold"

    bronze_stats: dict[str, Any] = {}
    silver_stats: dict[str, Any] = {}
    for src in ("psp", "payer_bank", "switch"):
        bronze_stats[src] = run_batch_ingest(
            source=src,
            raw_dir=raw_dir,
            bronze_dir=bronze_dir,
            quarantine_dir=quarantine_dir,
            checkpoint_dir=bronze_dir / "_checkpoints",
        )
        # Load ingested records for this date from bronze parquet
        import pyarrow.parquet as pq

        part_dir = bronze_dir / src / f"event_date={ds}"
        rows: list[dict[str, Any]] = []
        if part_dir.exists():
            for f in sorted(part_dir.glob("*.parquet")):
                rows.extend(pq.ParquetFile(f).read().to_pylist())
        silver_stats[src] = process_silver_records(
            records=rows,
            source=src,
            batch_date=ds,
            silver_dir=silver_dir,
            quarantine_dir=quarantine_dir,
            enforce_circuit_breaker=False,
        )

    recon_stats = run_reconciliation_to_disk(silver_dir=silver_dir, recon_dir=recon_dir, recon_date=ds)
    gold_stats = load_gold_local(silver_dir=silver_dir, recon_dir=recon_dir, gold_dir=gold_dir)
    return {
        "ds": ds,
        "bronze": bronze_stats,
        "silver": silver_stats,
        "recon_matched": recon_stats["matched_count"],
        "recon_breaks": recon_stats["broken_ref_count"],
        "gold": gold_stats,
    }
