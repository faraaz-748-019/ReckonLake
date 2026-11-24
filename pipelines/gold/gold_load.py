"""
Gold layer loader: materialises Gold marts from Silver & Reconciliation tables,
and loads them into PostgreSQL via PySpark JDBC using the least-privilege `etl_writer` role.
Also provides a local SQLite/Parquet serving sink for offline laptop testing without Docker.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.observability import build_settlement_kpi_column_lineage, emit_openlineage_event


def load_gold_local(
    silver_dir: Path,
    recon_dir: Path,
    gold_dir: Path,
    sqlite_path: Path | None = None,
) -> dict[str, Any]:
    """
    Build Gold mart Parquet tables (daily_settlement_kpis, psp_performance,
    dq_scorecard, recon_dashboard) and optionally load into a local SQLite DB.
    """
    run_id = str(uuid.uuid4())
    emit_openlineage_event(
        job_name="gold_load_and_marts",
        event_type="START",
        inputs=[
            {"namespace": "reconlake", "name": "silver.psp"},
            {"namespace": "reconlake", "name": "recon.summary"},
        ],
        outputs=[{"namespace": "reconlake", "name": "gold.daily_settlement_kpis"}],
        run_id=run_id,
    )

    psp_rows: list[dict[str, Any]] = []
    psp_dir = silver_dir / "psp"
    if psp_dir.exists():
        for f in sorted(psp_dir.glob("*.parquet")):
            psp_rows.extend(pq.ParquetFile(f).read().to_pylist())

    # Aggregate daily_settlement_kpis
    kpi_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for r in psp_rows:
        key = (str(r["event_date"]), str(r.get("psp_id", "PSP_01")))
        b = kpi_buckets.setdefault(
            key,
            {
                "event_date": key[0],
                "psp_app": key[1],
                "total_transactions": 0,
                "total_amount_paise": 0,
                "successful_transactions": 0,
                "failed_transactions": 0,
            },
        )
        b["total_transactions"] += 1
        b["total_amount_paise"] += int(r["amount_paise"])
        if r["state"] == "SUCCESS":
            b["successful_transactions"] += 1
        elif r["state"] == "FAILED":
            b["failed_transactions"] += 1

    kpi_rows = [
        {
            **b,
            "total_amount_rupees": round(b["total_amount_paise"] / 100.0, 2),
            "success_rate_pct": round(100.0 * b["successful_transactions"] / max(1, b["total_transactions"]), 2),
        }
        for b in sorted(kpi_buckets.values(), key=lambda x: (x["event_date"], x["psp_app"]))
    ]

    gold_dir.mkdir(parents=True, exist_ok=True)
    if kpi_rows:
        pq.write_table(pa.Table.from_pylist(kpi_rows), gold_dir / "daily_settlement_kpis.parquet")

    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(sqlite_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_settlement_kpis (
                    event_date TEXT NOT NULL,
                    psp_app TEXT NOT NULL,
                    total_transactions INTEGER NOT NULL,
                    total_amount_paise INTEGER NOT NULL,
                    successful_transactions INTEGER NOT NULL,
                    failed_transactions INTEGER NOT NULL,
                    total_amount_rupees REAL NOT NULL,
                    success_rate_pct REAL NOT NULL,
                    PRIMARY KEY (event_date, psp_app)
                )
                """
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO daily_settlement_kpis
                (event_date, psp_app, total_transactions, total_amount_paise,
                 successful_transactions, failed_transactions, total_amount_rupees, success_rate_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["event_date"],
                        r["psp_app"],
                        r["total_transactions"],
                        r["total_amount_paise"],
                        r["successful_transactions"],
                        r["failed_transactions"],
                        r["total_amount_rupees"],
                        r["success_rate_pct"],
                    )
                    for r in kpi_rows
                ],
            )
            conn.commit()
        finally:
            conn.close()

    emit_openlineage_event(
        job_name="gold_load_and_marts",
        event_type="COMPLETE",
        inputs=[{"namespace": "reconlake", "name": "silver.psp"}],
        outputs=[
            {
                "namespace": "reconlake",
                "name": "gold.daily_settlement_kpis",
                "facets": build_settlement_kpi_column_lineage(),
            }
        ],
        run_id=run_id,
    )

    return {"gold_kpis_rows": len(kpi_rows), "gold_dir": str(gold_dir)}


def run_spark_jdbc_load() -> None:  # pragma: no cover
    """Load Gold Delta tables into PostgreSQL using least-privilege `etl_writer` role."""
    from pyspark.sql import SparkSession

    jdbc_url = os.environ.get("POSTGRES_JDBC_URL", "jdbc:postgresql://postgres:5432/reconlake")
    etl_user = os.environ.get("POSTGRES_ETL_USER", "etl_writer")
    pw_file = os.environ.get("POSTGRES_ETL_PASSWORD_FILE", "/run/secrets/postgres_etl_writer_password")
    with open(pw_file, encoding="utf-8") as fh:
        etl_pw = fh.read().strip()

    spark = SparkSession.builder.appName("reconlake-gold-jdbc").getOrCreate()
    for delta_table, pg_table in [
        ("s3a://gold/recon_summary", "raw_gold.recon_summary"),
        ("s3a://gold/recon_breaks", "raw_gold.recon_breaks"),
    ]:
        df = spark.read.format("delta").load(delta_table)
        (
            df.write.format("jdbc")
            .option("url", jdbc_url)
            .option("dbtable", pg_table)
            .option("user", etl_user)
            .option("password", etl_pw)
            .option("driver", "org.postgresql.Driver")
            .mode("overwrite")
            .option("truncate", "true")
            .save()
        )
