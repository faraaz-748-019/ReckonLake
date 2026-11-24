"""Airflow DAG: gold_load_and_dbt — data-aware Gold load + dbt build after Silver DQ gate & Recon."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dags.common import DATASET_GOLD_READY, DATASET_RECON_READY, DATASET_SILVER_DQ_PASSED, DEFAULT_ARGS

try:
    from airflow import DAG
    from airflow.operators.bash import BashOperator
    from airflow.operators.python import PythonOperator
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    BashOperator = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]


def run_gold_load_task(ds: str = "2026-11-01", **_: object) -> dict[str, object]:
    from pipelines.gold.gold_load import load_gold_local

    return load_gold_local(
        silver_dir=Path("data/silver"),
        recon_dir=Path("data/recon") / ds,
        gold_dir=Path("data/gold"),
        sqlite_path=Path("data/gold/serving.db"),
    )


if DAG is not None:
    with DAG(
        dag_id="gold_load_and_dbt",
        default_args=DEFAULT_ARGS,
        schedule=[DATASET_SILVER_DQ_PASSED, DATASET_RECON_READY],
        start_date=datetime(2026, 11, 1),
        catchup=False,
        max_active_runs=1,
        tags=["gold", "dbt"],
    ) as dag:
        t_gold = PythonOperator(task_id="gold_load", python_callable=run_gold_load_task)
        t_dbt = BashOperator(
            task_id="dbt_build",
            bash_command="cd /opt/airflow/dbt && dbt build",
            outlets=[DATASET_GOLD_READY],
        )
        t_gold >> t_dbt
