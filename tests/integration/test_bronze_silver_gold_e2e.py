"""Integration & security abuse-case tests."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import pytest

from pipelines.bronze.streaming_ingest import ingest_records_to_bronze
from pipelines.recon.recon_engine import run_reconciliation_to_disk
from scripts.demo import run_demo
from security.audit_chain import AuditChain

RAW_VPA_RE = re.compile(r"[a-zA-Z0-9._-]+@(okaxis|okicici|oksbi|okhdfcbank|ybl|paytm|upi)\b")
RAW_PHONE_RE = re.compile(r"\+91\d{10}")


@pytest.mark.integration
def test_end_to_end_demo_story(tmp_path: Path) -> None:
    res = run_demo(count=500, work_dir=tmp_path / "demo")
    assert res["reconciliation"]["total_unique_refs"] == 500
    assert res["crypto_shredding"]["decrypt_after_shred_blocked"] is True
    assert res["audit_chain"]["valid"] is True
    assert res["gold"]["gold_kpis_rows"] >= 1


@pytest.mark.integration
def test_abuse_no_raw_pii_in_logs_or_bronze(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    records = [
        {
            "psp_event_id": "ev-001",
            "shared_ref": "UPI0001",
            "txn_id": "t-001",
            "type": "P2P",
            "state": "SUCCESS",
            "amount_paise": 1500,
            "payer_vpa": "alice123@okaxis",
            "payee_vpa": "bob456@ybl",
            "timestamp": "2026-11-01T00:00:00+00:00",
            "failure_code": "NONE",
            "psp_id": "PSP_GPAY",
        }
    ]
    bronze_dir = tmp_path / "bronze"
    q_dir = tmp_path / "quarantine"
    ingest_records_to_bronze(records, source="psp", bronze_dir=bronze_dir, quarantine_dir=q_dir)

    # Scan logs for raw VPA or phone patterns
    for rec in caplog.records:
        msg = rec.getMessage()
        assert not RAW_VPA_RE.search(msg), f"Raw VPA leaked in logs: {msg}"
        assert not RAW_PHONE_RE.search(msg), f"Raw phone leaked in logs: {msg}"

    # Scan Bronze Parquet contents to ensure raw VPA never landed
    import pyarrow.parquet as pq

    files = list((bronze_dir / "psp").rglob("*.parquet"))
    assert len(files) == 1
    rows = pq.ParquetFile(files[0]).read().to_pylist()
    assert len(rows) == 1
    assert "alice123@okaxis" not in str(rows[0])
    assert len(rows[0]["payer_vpa_token"]) == 64


@pytest.mark.integration
def test_abuse_sql_injection_blocked_by_parameterised_queries(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, val INTEGER)")
    conn.execute("INSERT INTO t VALUES ('safe', 100)")
    conn.commit()

    payload = "' OR '1'='1"
    rows = conn.execute("SELECT * FROM t WHERE id = ?", (payload,)).fetchall()
    conn.close()
    assert rows == []


@pytest.mark.integration
def test_abuse_audit_tampering_caught_after_save(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.json"
    chain = AuditChain()
    chain.append("KEY_ACCESS", "spark", "token:abc", {"ok": True})
    chain.append("SHREDDING", "privacy", "token:abc", {"done": True})
    chain.save(audit_path)

    # Simulate DB/file tamper
    tampered = audit_path.read_text(encoding="utf-8").replace("privacy", "attacker")
    audit_path.write_text(tampered, encoding="utf-8")

    reloaded = AuditChain.load(audit_path)
    valid, bad_idx = reloaded.verify()
    assert not valid and bad_idx == 1


@pytest.mark.integration
def test_recon_creates_exception_queue_files(tmp_path: Path) -> None:
    from generator.producer import UPIGenerator
    from pipelines.silver.silver_pipeline import process_silver_records

    gen = UPIGenerator(seed=11, count=100, defect_profile="medium", fraud_profile="none")
    psp, bank, switch, _, _ = next(gen.generate())
    silver_dir = tmp_path / "silver"
    q_dir = tmp_path / "quarantine"
    for s, evs in [("psp", psp), ("payer_bank", bank), ("switch", switch)]:
        process_silver_records(evs, s, "2026-11-01", silver_dir, q_dir, dq_threshold=0.0, enforce_circuit_breaker=False)

    recon_dir = tmp_path / "recon"
    run_reconciliation_to_disk(silver_dir, recon_dir, "2026-11-01")
    assert (recon_dir / "exception_queue.json").exists()
    assert (recon_dir / "exception_history.json").exists()
