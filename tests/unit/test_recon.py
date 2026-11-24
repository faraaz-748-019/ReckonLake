"""Unit tests for the three-way reconciliation engine and exception queue."""

from __future__ import annotations

import pytest

from generator.producer import UPIGenerator
from pipelines.recon.exception_queue import ExceptionQueue, ExceptionStatus
from pipelines.recon.recon_engine import evaluate_against_ground_truth, reconcile_three_way


@pytest.mark.unit
def test_three_way_reconciliation_breaks_and_ground_truth() -> None:
    gen = UPIGenerator(seed=42, count=500, defect_profile="medium", fraud_profile="none")
    psp, bank, switch, _, defect_labels = next(gen.generate())

    res = reconcile_three_way(psp, bank, switch, recon_date="2026-11-01")
    assert res["matched_count"] + res["broken_ref_count"] == res["total_unique_refs"]

    gt_dicts = [
        {"shared_ref": d.shared_ref, "defect_type": d.defect_type.value}
        for d in defect_labels
    ]
    metrics = evaluate_against_ground_truth(res["breaks"], gt_dicts)
    for cat in ("MISSING_IN_PSP", "MISSING_IN_BANK", "MISSING_IN_SWITCH", "AMOUNT_MISMATCH"):
        if cat in metrics:
            assert metrics[cat]["recall"] == 1.0, f"Missed break in {cat}: {metrics[cat]}"


@pytest.mark.unit
def test_exception_queue_workflow_and_audit() -> None:
    eq = ExceptionQueue()
    brk = {
        "break_id": "brk-001",
        "shared_ref": "UPI0001",
        "category": "AMOUNT_MISMATCH",
        "severity": "HIGH",
        "suggested_action": "Hold settlement",
    }
    item = eq.enqueue(brk)
    assert item.status == ExceptionStatus.OPEN

    eq.transition("brk-001", ExceptionStatus.INVESTIGATING, actor="ops_user", assignee="ops_user")
    eq.transition("brk-001", ExceptionStatus.RESOLVED, actor="ops_user", note="Adjusted ₹10")
    assert eq.items["brk-001"].status == ExceptionStatus.RESOLVED
    assert len(eq.history) == 3

    with pytest.raises(ValueError):
        eq.transition("brk-001", ExceptionStatus.OPEN, actor="ops_user")

    valid, bad_idx = eq.audit_chain.verify()
    assert valid and bad_idx is None
