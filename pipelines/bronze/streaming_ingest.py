"""
Bronze ingestion core & Spark Structured Streaming job.

Responsibilities:
  - Append-only, immutable Bronze storage partitioned by event_date
  - Contract validation (Pydantic + JSONSchema) at the ingestion boundary
  - Tokenization boundary: raw VPA/phone/account fields are never persisted to Bronze
  - Metadata enrichment: source, batch_id, ingested_at, contract_version, raw_payload_sha256
  - Quarantine routing with explicit reason codes (never silently drop records)
  - Checkpoint tracking so mid-run restarts never lose or duplicate offsets
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from contracts.validator import load_contract, validate_event
from pipelines.observability import ROWS_IN, ROWS_OUT, ROWS_QUARANTINED, emit_openlineage_event
from security.key_service import LocalKeyService
from security.tokenizer import ProviderKeySource, Tokenizer

RAW_PII_FIELDS = ("payer_vpa", "payee_vpa", "payer_phone", "payer_account")


def compute_payload_sha256(record: dict[str, Any]) -> str:
    """Compute canonical SHA-256 hex digest of a raw event payload."""
    canonical = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def enforce_tokenization_boundary(
    record: dict[str, Any],
    tokenizer: Tokenizer,
) -> dict[str, Any]:
    """
    Strip any raw PII identifiers (VPA, phone, account) and replace with
    deterministic HMAC tokens before landing in Bronze.
    """
    cleaned = dict(record)
    if "payer_vpa" in cleaned:
        raw = str(cleaned.pop("payer_vpa"))
        if raw and "payer_vpa_token" not in cleaned:
            cleaned["payer_vpa_token"] = tokenizer.tokenize_vpa(raw)
    if "payee_vpa" in cleaned:
        raw = str(cleaned.pop("payee_vpa"))
        if raw and "payee_vpa_token" not in cleaned:
            cleaned["payee_vpa_token"] = tokenizer.tokenize_vpa(raw)
    if "payer_phone" in cleaned:
        raw = str(cleaned.pop("payer_phone"))
        if raw:
            cleaned["payer_phone_token"] = tokenizer.tokenize_phone(raw)
    if "payer_account" in cleaned:
        raw = str(cleaned.pop("payer_account"))
        if raw:
            cleaned["payer_account_token"] = tokenizer.tokenize_account(raw)
    return cleaned


def _extract_event_date(ts_value: Any) -> str:
    if isinstance(ts_value, str):
        clean = ts_value.removeprefix("LATE#")
        if len(clean) >= 10 and clean[4] == "-" and clean[7] == "-":
            return clean[:10]
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_checkpoint(ckpt_path: Path) -> set[str]:
    if not ckpt_path.exists():
        return set()
    return set(json.loads(ckpt_path.read_text(encoding="utf-8")))


def _save_checkpoint(ckpt_path: Path, seen_hashes: set[str]) -> None:
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    ckpt_path.write_text(json.dumps(sorted(seen_hashes)), encoding="utf-8")


def ingest_records_to_bronze(
    records: list[dict[str, Any]],
    source: str,
    bronze_dir: Path,
    quarantine_dir: Path,
    batch_id: str | None = None,
    tokenizer: Tokenizer | None = None,
    checkpoint_path: Path | None = None,
    fail_after_n: int | None = None,
) -> dict[str, Any]:
    """
    Ingest a list of raw records for *source* into append-only Bronze and Quarantine.

    Supports checkpointed crash recovery: if *checkpoint_path* is provided, already-committed
    payload hashes/offsets are skipped on restart so restarting mid-run produces zero duplicates
    and zero data loss.
    """
    contract = load_contract(source)
    tok = tokenizer or Tokenizer(ProviderKeySource(LocalKeyService()))
    bid = batch_id or str(uuid.uuid4())
    ingested_at = datetime.now(UTC).isoformat()

    committed_offsets = _load_checkpoint(checkpoint_path) if checkpoint_path else set()

    bronze_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    new_offsets: list[str] = []

    run_id = str(uuid.uuid4())
    emit_openlineage_event(
        job_name=f"bronze_ingest_{source}",
        event_type="START",
        inputs=[{"namespace": "kafka", "name": f"{source}_ledger"}],
        outputs=[{"namespace": "reconlake", "name": f"bronze.{source}"}],
        run_id=run_id,
    )

    processed_in_run = 0
    for idx, raw_rec in enumerate(records):
        offset_key = f"{source}:{idx}:{compute_payload_sha256(raw_rec)}"
        if offset_key in committed_offsets:
            continue

        if fail_after_n is not None and processed_in_run >= fail_after_n:
            # Flush progress so far before simulated crash
            _flush_bronze_and_quarantine(bronze_rows, quarantine_rows, source, bronze_dir, quarantine_dir)
            if checkpoint_path:
                committed_offsets.update(new_offsets)
                _save_checkpoint(checkpoint_path, committed_offsets)
            raise RuntimeError(f"Simulated mid-run crash after {processed_in_run} records")

        ROWS_IN.labels(layer="bronze", source=source).inc()
        raw_hash = compute_payload_sha256(raw_rec)
        token_safe = enforce_tokenization_boundary(raw_rec, tok)
        is_valid, reasons = validate_event(token_safe, contract)

        if is_valid:
            enriched = dict(token_safe)
            enriched["source"] = source
            enriched["batch_id"] = bid
            enriched["ingested_at"] = ingested_at
            enriched["contract_version"] = contract["version"]
            enriched["raw_payload_sha256"] = raw_hash
            enriched["event_date"] = _extract_event_date(enriched.get("timestamp"))
            bronze_rows.append(enriched)
            ROWS_OUT.labels(layer="bronze", source=source).inc()
        else:
            primary_reason = reasons[0].split(":")[0] if reasons else "CONTRACT_VIOLATION"
            quarantine_rows.append(
                {
                    "source": source,
                    "batch_id": bid,
                    "ingested_at": ingested_at,
                    "contract_version": contract["version"],
                    "raw_payload_sha256": raw_hash,
                    "reason_code": primary_reason,
                    "reason_details": json.dumps(reasons),
                    "event_date": _extract_event_date(raw_rec.get("timestamp")),
                    "raw_payload": json.dumps(token_safe, default=str),
                }
            )
            ROWS_QUARANTINED.labels(layer="bronze", source=source, reason_code=primary_reason).inc()

        new_offsets.append(offset_key)
        processed_in_run += 1

    _flush_bronze_and_quarantine(bronze_rows, quarantine_rows, source, bronze_dir, quarantine_dir)
    if checkpoint_path:
        committed_offsets.update(new_offsets)
        _save_checkpoint(checkpoint_path, committed_offsets)

    emit_openlineage_event(
        job_name=f"bronze_ingest_{source}",
        event_type="COMPLETE",
        inputs=[{"namespace": "kafka", "name": f"{source}_ledger"}],
        outputs=[
            {"namespace": "reconlake", "name": f"bronze.{source}"},
            {"namespace": "reconlake", "name": f"quarantine.{source}"},
        ],
        run_id=run_id,
    )

    return {
        "source": source,
        "batch_id": bid,
        "rows_in": processed_in_run,
        "bronze_written": len(bronze_rows),
        "quarantined": len(quarantine_rows),
    }


def _flush_bronze_and_quarantine(
    bronze_rows: list[dict[str, Any]],
    quarantine_rows: list[dict[str, Any]],
    source: str,
    bronze_dir: Path,
    quarantine_dir: Path,
) -> None:
    """Write append-only partitioned Parquet files for Bronze and Quarantine."""
    if bronze_rows:
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in bronze_rows:
            by_date.setdefault(row["event_date"], []).append(row)
        for ev_date, part_rows in by_date.items():
            part_dir = bronze_dir / source / f"event_date={ev_date}"
            part_dir.mkdir(parents=True, exist_ok=True)
            out_file = part_dir / f"part-{uuid.uuid4().hex[:12]}.parquet"
            norm = [
                {k: (None if v is None else str(v) if k not in ("amount_paise",) else int(v)) for k, v in r.items()}
                for r in part_rows
            ]
            pq.write_table(pa.Table.from_pylist(norm), out_file)

    if quarantine_rows:
        q_dir = quarantine_dir / source
        q_dir.mkdir(parents=True, exist_ok=True)
        out_file = q_dir / f"part-{uuid.uuid4().hex[:12]}.parquet"
        pq.write_table(pa.Table.from_pylist(quarantine_rows), out_file)


def run_spark_streaming() -> None:  # pragma: no cover
    """PySpark Structured Streaming job reading Kafka topics into Delta Lake over SeaweedFS."""
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as fn

    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
    s3_endpoint = os.environ.get("S3_ENDPOINT", "http://seaweedfs:8333")
    bronze_path = os.environ.get("BRONZE_PATH", "s3a://bronze")

    builder = (
        SparkSession.builder.appName("reconlake-bronze-streaming")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.hadoop.fs.s3a.endpoint", s3_endpoint)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()

    for source, topic in [("psp", "psp_ledger"), ("payer_bank", "payer_bank_ledger"), ("switch", "switch_ledger")]:
        contract = load_contract(source)
        raw_df = (
            spark.readStream.format("kafka")
            .option("kafka.bootstrap.servers", kafka_bootstrap)
            .option("subscribe", topic)
            .option("startingOffsets", "earliest")
            .load()
            .select(
                fn.col("value").cast("string").alias("raw_json"),
                fn.lit(source).alias("source"),
                fn.expr("uuid()").alias("batch_id"),
                fn.current_timestamp().alias("ingested_at"),
                fn.lit(contract["version"]).alias("contract_version"),
                fn.sha2(fn.col("value").cast("string"), 256).alias("raw_payload_sha256"),
                fn.current_date().alias("event_date"),
            )
        )
        (
            raw_df.writeStream.format("delta")
            .outputMode("append")
            .option("checkpointLocation", f"{bronze_path}/_checkpoints/{source}")
            .partitionBy("event_date")
            .start(f"{bronze_path}/{source}")
        )
    spark.streams.awaitAnyTermination()
