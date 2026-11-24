"""
Observability helpers for ReconLake pipelines:
  - Prometheus metrics (rows_in, rows_out, rows_quarantined, dq_score, processing_lag)
  - OpenLineage RunEvent emitter (dataset-level + column-level lineage for Marquez)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

ROWS_IN = Counter("reconlake_rows_in_total", "Total rows entering a pipeline layer", ["layer", "source"])
ROWS_OUT = Counter("reconlake_rows_out_total", "Total clean rows output from a layer", ["layer", "source"])
ROWS_QUARANTINED = Counter(
    "reconlake_rows_quarantined_total",
    "Total rows sent to quarantine",
    ["layer", "source", "reason_code"],
)
DQ_SCORE_GAUGE = Gauge("reconlake_dq_score", "Latest batch Data Quality Score (0..1)", ["source"])
PROCESSING_LAG = Histogram(
    "reconlake_stream_lag_seconds",
    "Event-time to processing-time lag in seconds",
    ["layer", "source"],
)
RECON_BREAKS_COUNTER = Counter(
    "reconlake_recon_breaks_total",
    "Total reconciliation breaks detected",
    ["category", "severity"],
)


# ---------------------------------------------------------------------------
# OpenLineage Emitter
# ---------------------------------------------------------------------------


def emit_openlineage_event(
    job_name: str,
    event_type: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    run_id: str | None = None,
    namespace: str = "reconlake",
    lineage_log_path: Path | None = None,
) -> dict[str, Any]:
    """
    Build and emit an OpenLineage RunEvent (START / COMPLETE / FAIL).
    Persists to local JSONL for offline auditability and posts to Marquez
    if OPENLINEAGE_URL is configured.
    """
    rid = run_id or str(uuid.uuid4())
    event: dict[str, Any] = {
        "eventType": event_type,
        "eventTime": datetime.now(UTC).isoformat(),
        "run": {"runId": rid},
        "job": {"namespace": namespace, "name": job_name},
        "inputs": inputs,
        "outputs": outputs,
        "producer": "https://github.com/reconlake/reconlake",
        "schemaURL": "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent",
    }

    target_path = lineage_log_path or Path(os.environ.get("LINEAGE_LOG_PATH", "data/lineage/events.jsonl"))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")

    ol_url = os.environ.get("OPENLINEAGE_URL")
    if ol_url:
        try:
            httpx.post(f"{ol_url.rstrip('/')}/api/v1/lineage", json=event, timeout=2.0)
        except Exception as exc:
            logging.debug("OpenLineage endpoint unreachable: %s", exc)

    return event


def build_settlement_kpi_column_lineage() -> dict[str, Any]:
    """Column-level lineage facet mapping Silver PSP fields -> Gold daily_settlement_kpis."""
    return {
        "columnLineage": {
            "_producer": "https://github.com/reconlake/reconlake",
            "_schemaURL": "https://openlineage.io/spec/facets/1-0-2/ColumnLineageDatasetFacet.json",
            "fields": {
                "event_date": {
                    "inputFields": [{"namespace": "reconlake", "name": "silver.psp", "field": "event_date"}],
                    "transformationType": "IDENTITY",
                },
                "total_transactions": {
                    "inputFields": [{"namespace": "reconlake", "name": "silver.psp", "field": "event_id"}],
                    "transformationType": "AGGREGATION",
                },
                "total_amount_rupees": {
                    "inputFields": [{"namespace": "reconlake", "name": "silver.psp", "field": "amount_paise"}],
                    "transformationType": "AGGREGATION",
                },
                "success_rate_pct": {
                    "inputFields": [{"namespace": "reconlake", "name": "silver.psp", "field": "state"}],
                    "transformationType": "AGGREGATION",
                },
            },
        }
    }


class JobTimer:
    """Context manager to time pipeline stages."""

    def __init__(self) -> None:
        self.start = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.start
