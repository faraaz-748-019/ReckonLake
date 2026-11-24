"""Airflow DAG: ingest_batch — idempotent, backfillable Bronze file-drop ingestion."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dags.common import DATASET_BRONZE_READY, DEFAULT_ARGS

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]


def ingest_source_task(source: str, **_: object) -> dict[str, object]:
    from pipelines.bronze.batch_ingest import run_batch_ingest

    return run_batch_ingest(
        source=source,
        raw_dir=Path("data/raw"),
        bronze_dir=Path("data/bronze"),
        quarantine_dir=Path("data/quarantine"),
        checkpoint_dir=Path("data/bronze/_checkpoints"),
    )


if DAG is not None:
    with DAG(
        dag_id="ingest_batch",
        default_args=DEFAULT_ARGS,
        schedule="0 * * * *",
        start_date=datetime(2026, 11, 1),
        catchup=True,
        max_active_runs=1,
        tags=["bronze", "ingestion"],
    ) as dag:
        t_psp = PythonOperator(
            task_id="ingest_psp",
            python_callable=ingest_source_task,
            op_kwargs={"source": "psp"},
        )
        t_bank = PythonOperator(
            task_id="ingest_payer_bank",
            python_callable=ingest_source_task,
            op_kwargs={"source": "payer_bank"},
        )
        t_switch = PythonOperator(
            task_id="ingest_switch",
            python_callable=ingest_source_task,
            op_kwargs={"source": "switch"},
            outlets=[DATASET_BRONZE_READY],
        )
        [t_psp, t_bank] >> t_switch
