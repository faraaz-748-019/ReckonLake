"""Airflow DAG: silver_pipeline — triggered by Bronze dataset; gates Gold via DQ circuit breaker."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dags.common import DATASET_BRONZE_READY, DATASET_SILVER_DQ_PASSED, DEFAULT_ARGS

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]


def run_silver_task(source: str, ds: str = "2026-11-01", **_: object) -> dict[str, object]:
    import pyarrow.parquet as pq

    from pipelines.silver.silver_pipeline import process_silver_records

    part_dir = Path("data/bronze") / source / f"event_date={ds}"
    rows = []
    if part_dir.exists():
        for f in sorted(part_dir.glob("*.parquet")):
            rows.extend(pq.ParquetFile(f).read().to_pylist())
    return process_silver_records(
        records=rows,
        source=source,
        batch_date=ds,
        silver_dir=Path("data/silver"),
        quarantine_dir=Path("data/quarantine"),
    )


if DAG is not None:
    with DAG(
        dag_id="silver_pipeline",
        default_args=DEFAULT_ARGS,
        schedule=[DATASET_BRONZE_READY],
        start_date=datetime(2026, 11, 1),
        catchup=False,
        max_active_runs=1,
        tags=["silver", "quality-gate"],
    ) as dag:
        s_psp = PythonOperator(task_id="silver_psp", python_callable=run_silver_task, op_kwargs={"source": "psp"})
        s_bank = PythonOperator(
            task_id="silver_payer_bank", python_callable=run_silver_task, op_kwargs={"source": "payer_bank"}
        )
        s_switch = PythonOperator(
            task_id="silver_switch",
            python_callable=run_silver_task,
            op_kwargs={"source": "switch"},
            outlets=[DATASET_SILVER_DQ_PASSED],
        )
        [s_psp, s_bank] >> s_switch
