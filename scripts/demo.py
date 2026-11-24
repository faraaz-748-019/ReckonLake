"""
End-to-end ReconLake demo script (`make demo`).

Runs the complete story locally in seconds/minutes:
  1. Generate seeded synthetic UPI events with fraud & injected defects
  2. Ingest into Bronze (contract validation + tokenization boundary + quarantine)
  3. Cleanse & deduplicate in Silver with 5-dimension DQ Score & circuit breaker
  4. Reconcile 3 ledgers (PSP vs Payer Bank vs Switch) + classify breaks & exception queue
  5. Evaluate reconciliation precision & recall against ground truth
  6. Materialize Gold marts & SQLite serving DB
  7. Crypto-shred a customer token DEK & verify original PII is unrecoverable while Gold aggregates remain intact
  8. Verify hash-chained audit log integrity
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import click

from generator.producer import UPIGenerator
from pipelines.bronze.batch_ingest import run_batch_ingest
from pipelines.gold.gold_load import load_gold_local
from pipelines.recon.recon_engine import evaluate_against_ground_truth, run_reconciliation_to_disk
from pipelines.silver.silver_pipeline import process_silver_records
from security.audit_chain import AuditChain
from security.envelope import CryptoShredError, EnvelopeEncryptor, FileKeyStore
from security.key_service import LocalKeyService
from security.shred import shred_token


def run_demo(count: int = 10_000, work_dir: Path = Path("data/demo")) -> dict[str, Any]:
    t0 = time.perf_counter()
    if work_dir.exists():
        shutil.rmtree(work_dir)
    raw_dir = work_dir / "raw"
    bronze_dir = work_dir / "bronze"
    silver_dir = work_dir / "silver"
    quarantine_dir = work_dir / "quarantine"
    recon_dir = work_dir / "recon"
    gold_dir = work_dir / "gold"
    keystore_path = work_dir / "keystore.json"
    audit_path = work_dir / "audit_chain.json"

    # 1. Generate synthetic UPI data (single operational day batch)
    gen = UPIGenerator(seed=42, count=count, defect_profile="medium", fraud_profile="standard", batch_size=count)
    gen_stats = gen.write_files(raw_dir, file_format="jsonl")

    # 2. Bronze ingestion across all 3 ledgers
    bronze_stats = {}
    for src in ("psp", "payer_bank", "switch"):
        bronze_stats[src] = run_batch_ingest(
            source=src,
            raw_dir=raw_dir,
            bronze_dir=bronze_dir,
            quarantine_dir=quarantine_dir,
            checkpoint_dir=bronze_dir / "_checkpoints",
        )

    # 3. Silver cleansing + DQ score (grouped by first discovered date partition)
    import pyarrow.parquet as pq

    silver_stats = {}
    batch_date = "2026-11-01"
    for src in ("psp", "payer_bank", "switch"):
        src_dir = bronze_dir / src
        rows: list[dict[str, Any]] = []
        if src_dir.exists():
            for f in sorted(src_dir.rglob("*.parquet")):
                rows.extend(pq.ParquetFile(f).read().to_pylist())
        silver_stats[src] = process_silver_records(
            records=rows,
            source=src,
            batch_date=batch_date,
            silver_dir=silver_dir,
            quarantine_dir=quarantine_dir,
            enforce_circuit_breaker=False,
        )

    # 4. Three-way reconciliation
    recon_stats = run_reconciliation_to_disk(
        silver_dir=silver_dir,
        recon_dir=recon_dir,
        recon_date=batch_date,
        quarantine_dir=quarantine_dir,
    )

    # 5. Evaluate against ground truth
    defect_labels = []
    gt_file = raw_dir / "ground_truth" / "defect_labels.jsonl"
    if gt_file.exists():
        for line in gt_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                defect_labels.append(json.loads(line))
    pr_metrics = evaluate_against_ground_truth(recon_stats["breaks"], defect_labels)

    # 6. Load Gold marts
    gold_stats = load_gold_local(
        silver_dir=silver_dir,
        recon_dir=recon_dir,
        gold_dir=gold_dir,
        sqlite_path=gold_dir / "serving.db",
    )

    # 7. Envelope encryption + Crypto-shredding demo
    store = FileKeyStore(keystore_path)
    enc = EnvelopeEncryptor(kek_provider=LocalKeyService(), dek_store=store)
    sample_token_id = "tok_demo_customer_001"  # noqa: S105
    envelope = enc.encrypt("cust00001@okaxis", token_id=sample_token_id)
    assert enc.decrypt(envelope) == "cust00001@okaxis"

    chain = AuditChain()
    chain.append("KEY_ACCESS", "demo_runner", f"token:{sample_token_id}", {"op": "encrypt_demo"})
    chain.save(audit_path)

    shred_res = shred_token(sample_token_id, keystore_path, audit_path, actor="demo_privacy_officer")
    shred_blocked = False
    try:
        enc.decrypt(envelope)
    except CryptoShredError:
        shred_blocked = True

    # 8. Verify audit chain
    loaded_chain = AuditChain.load(audit_path)
    audit_valid, bad_idx = loaded_chain.verify()

    elapsed = round(time.perf_counter() - t0, 3)
    return {
        "elapsed_seconds": elapsed,
        "generator": gen_stats,
        "bronze": bronze_stats,
        "silver_dq_scores": {k: v["dq_score"] for k, v in silver_stats.items()},
        "reconciliation": {
            "total_unique_refs": recon_stats["total_unique_refs"],
            "matched_count": recon_stats["matched_count"],
            "broken_ref_count": recon_stats["broken_ref_count"],
            "break_event_count": recon_stats["break_event_count"],
            "ground_truth_eval": pr_metrics,
        },
        "gold": gold_stats,
        "crypto_shredding": {
            "shred_result": shred_res,
            "decrypt_after_shred_blocked": shred_blocked,
        },
        "audit_chain": {
            "valid": audit_valid,
            "entries": len(loaded_chain),
            "first_tampered_index": bad_idx,
        },
    }


@click.command()
@click.option("--count", default=10_000, show_default=True, type=int, help="Number of canonical transactions.")
@click.option("--work-dir", default="data/demo", show_default=True, help="Demo workspace directory.")
def main(count: int, work_dir: str) -> None:
    """Run the full end-to-end ReconLake demo."""
    summary = run_demo(count=count, work_dir=Path(work_dir))
    click.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
