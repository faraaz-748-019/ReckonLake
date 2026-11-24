"""Hypothesis property-based tests for UPI state machine, Silver conservation, and Recon invariants."""

from __future__ import annotations

import itertools
import random
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from generator.producer import VALID_TRANSITIONS, UPIGenerator, is_valid_transition, simulate_lifecycle
from pipelines.recon.recon_engine import reconcile_three_way
from pipelines.silver.silver_pipeline import process_silver_records


@pytest.mark.property
@given(seed=st.integers(min_value=0, max_value=100_000))
@settings(max_examples=50)
def test_state_machine_never_produces_illegal_transitions(seed: int) -> None:
    rng = random.Random(seed)
    path, _ = simulate_lifecycle(rng)
    assert len(path) >= 2
    for prev, nxt in itertools.pairwise(path):
        assert is_valid_transition(prev, nxt), f"Illegal edge {prev} -> {nxt}"
        assert nxt in VALID_TRANSITIONS[prev]


@pytest.mark.property
@given(
    dup_count=st.integers(min_value=0, max_value=10),
    bad_count=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=15, deadline=None)
def test_silver_conservation_invariant(dup_count: int, bad_count: int) -> None:
    gen = UPIGenerator(seed=42, count=30, defect_profile="none", fraud_profile="none")
    psp, _, _, _, _ = next(gen.generate())
    batch = list(psp)
    for i in range(dup_count):
        batch.append(dict(psp[i % len(psp)]))
    for i in range(bad_count):
        bad = dict(psp[i % len(psp)])
        bad["amount_paise"] = None
        batch.append(bad)

    with tempfile.TemporaryDirectory() as tmp:
        res = process_silver_records(
            batch,
            source="psp",
            batch_date="2026-11-01",
            silver_dir=Path(tmp) / "silver",
            quarantine_dir=Path(tmp) / "quarantine",
            dq_threshold=0.0,
            enforce_circuit_breaker=False,
        )
        assert res["rows_in"] == res["rows_out"] + res["rows_quarantined"] + res["rows_deduplicated"]


@pytest.mark.property
@given(seed=st.integers(min_value=1, max_value=500))
@settings(max_examples=15, deadline=None)
def test_recon_permutation_invariance_and_idempotency(seed: int) -> None:
    gen = UPIGenerator(seed=seed, count=40, defect_profile="medium", fraud_profile="none")
    psp, bank, switch, _, _ = next(gen.generate())

    fixed_now = datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC)
    r1 = reconcile_three_way(psp, bank, switch, recon_date="2026-11-01", reference_now=fixed_now)

    rng = random.Random(seed + 1)
    psp_shuf = list(psp)
    bank_shuf = list(bank)
    switch_shuf = list(switch)
    rng.shuffle(psp_shuf)
    rng.shuffle(bank_shuf)
    rng.shuffle(switch_shuf)

    r2 = reconcile_three_way(psp_shuf, bank_shuf, switch_shuf, recon_date="2026-11-01", reference_now=fixed_now)

    assert r1["matched_count"] == r2["matched_count"]
    assert r1["broken_ref_count"] == r2["broken_ref_count"]
    assert r1["matches"] == r2["matches"]
    assert r1["breaks"] == r2["breaks"]
    assert r1["matched_count"] + r1["broken_ref_count"] == r1["total_unique_refs"]
