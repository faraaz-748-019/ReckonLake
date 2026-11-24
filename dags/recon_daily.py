"""Airflow DAG: recon_daily — three-way reconciliation triggered after Silver DQ gate passes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dags.common import DATASET_RECON_READY, DATASET_SILVER_DQ_PASSED, DEFAULT_ARGS

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]


def run_recon_task(ds: str = "2026-11-01", **_: object) -> dict[str, object]:
    from pipelines.recon.recon_engine import run_reconciliation_to_disk

    return run_reconciliation_to_disk(
        silver_dir=Path("data/silver"),
        recon_dir=Path("data/recon") / ds,
        recon_date=ds,
    )


if DAG is not None:
    with DAG(
        dag_id="recon_daily",
        default_args=DEFAULT_ARGS,
        schedule=[DATASET_SILVER_DQ_PASSED],
        start_date=datetime(2026, 11, 1),
        catchup=False,
        max_active_runs=1,
        tags=["reconciliation"],
    ) as dag:
        PythonOperator(
            task_id="reconcile_three_way",
            python_callable=run_recon_task,
            outlets=[DATASET_RECON_READY],
        )
