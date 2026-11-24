"""Airflow DAG: backfill — idempotent historical date-range replay."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dags.common import DEFAULT_ARGS, run_day_pipeline

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]


def backfill_dates(dates: list[str], **_: Any) -> list[dict[str, Any]]:
    """Run idempotent pipeline slices for any list of dates (in any order)."""
    return [run_day_pipeline(ds) for ds in dates]


if DAG is not None:
    with DAG(
        dag_id="backfill",
        default_args=DEFAULT_ARGS,
        schedule=None,
        start_date=datetime(2026, 11, 1),
        catchup=False,
        tags=["backfill", "recovery"],
    ) as dag:
        PythonOperator(
            task_id="run_backfill",
            python_callable=backfill_dates,
            op_kwargs={"dates": ["{{ ds }}"]},
        )
