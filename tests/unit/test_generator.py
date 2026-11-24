"""Unit tests for the seeded synthetic UPI generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator.producer import UPIGenerator


@pytest.mark.unit
def test_same_seed_gives_identical_output(tmp_path: Path) -> None:
    g1 = UPIGenerator(seed=12345, count=200, defect_profile="medium", fraud_profile="standard")
    g2 = UPIGenerator(seed=12345, count=200, defect_profile="medium", fraud_profile="standard")

    d1 = tmp_path / "run1"
    d2 = tmp_path / "run2"
    g1.write_files(d1, file_format="jsonl")
    g2.write_files(d2, file_format="jsonl")

    for fname in (
        "psp_ledger.jsonl",
        "payer_bank_ledger.jsonl",
        "switch_ledger.jsonl",
        "ground_truth/fraud_labels.jsonl",
        "ground_truth/defect_labels.jsonl",
    ):
        assert (d1 / fname).read_text(encoding="utf-8") == (d2 / fname).read_text(encoding="utf-8")


@pytest.mark.unit
def test_defect_rates_within_tolerance(tmp_path: Path) -> None:
    gen = UPIGenerator(seed=99, count=1000, defect_profile="medium", fraud_profile="none")
    out = tmp_path / "rates"
    gen.write_files(out, file_format="jsonl")

    labels = [
        json.loads(line)
        for line in (out / "ground_truth" / "defect_labels.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_type: dict[str, int] = {}
    for lbl in labels:
        by_type[lbl["defect_type"]] = by_type.get(lbl["defect_type"], 0) + 1

    # Medium duplicate rate is 0.02 across 3 ledgers -> ~60 duplicates for 1000 txns
    assert 35 <= by_type.get("DUPLICATE_EVENT", 0) <= 90
    assert 15 <= by_type.get("NULL_KEY", 0) <= 50
    assert 5 <= by_type.get("AMOUNT_MISMATCH", 0) <= 25


@pytest.mark.unit
def test_shared_ref_links_all_three_ledgers(tmp_path: Path) -> None:
    gen = UPIGenerator(seed=7, count=50, defect_profile="none", fraud_profile="none")
    out = tmp_path / "clean"
    stats = gen.write_files(out, file_format="both")

    assert stats["throughput_events_per_sec"] > 0
    assert (out / "psp_ledger.parquet").exists()
    psp_refs = {json.loads(line)["shared_ref"] for line in (out / "psp_ledger.jsonl").read_text().splitlines()}
    bank_refs = {json.loads(line)["shared_ref"] for line in (out / "payer_bank_ledger.jsonl").read_text().splitlines()}
    switch_refs = {json.loads(line)["shared_ref"] for line in (out / "switch_ledger.jsonl").read_text().splitlines()}
    assert len(psp_refs) == 50
    assert psp_refs == bank_refs == switch_refs
