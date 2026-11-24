"""Airflow DAG: dq_report — daily Data Quality Scorecard & SLO summary."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from dags.common import DEFAULT_ARGS

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]


def compile_dq_report(**_: object) -> dict[str, object]:
    dq_dir = Path("data/silver/_dq_scores")
    scores = []
    if dq_dir.exists():
        for f in sorted(dq_dir.glob("*.json")):
            scores.append(json.loads(f.read_text(encoding="utf-8")))
    summary = {"batches_evaluated": len(scores), "scores": scores}
    out = Path("data/gold/dq_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if DAG is not None:
    with DAG(
        dag_id="dq_report",
        default_args=DEFAULT_ARGS,
        schedule="0 6 * * *",
        start_date=datetime(2026, 11, 1),
        catchup=False,
        tags=["quality", "slo"],
    ) as dag:
        PythonOperator(task_id="compile_dq_report", python_callable=compile_dq_report)
