"""Unit tests for YAML data contracts, validation, and breaking-change detection."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from contracts.compat import check_breaking_change, is_breaking_allowed
from contracts.validator import load_contract, validate_event
from generator.producer import UPIGenerator


@pytest.mark.unit
def test_contract_validation_valid_event() -> None:
    gen = UPIGenerator(seed=1, count=10, defect_profile="none", fraud_profile="none")
    psp_ev, bank_ev, switch_ev, _, _ = next(gen.generate())

    for src, events in [("psp", psp_ev), ("payer_bank", bank_ev), ("switch", switch_ev)]:
        contract = load_contract(src)
        for ev in events:
            ok, reasons = validate_event(ev, contract)
            assert ok, f"Expected valid {src} event, got {reasons}"


@pytest.mark.unit
def test_contract_validation_catches_violations() -> None:
    contract = load_contract("psp")
    bad_event = {
        "psp_event_id": "e1",
        "shared_ref": None,
        "txn_id": "t1",
        "type": "INVALID_TYPE",
        "state": "SUCCESS",
        "amount_paise": -50,
        "payer_vpa_token": "alice@okaxis",  # raw VPA PII exposure!
        "payee_vpa_token": "a" * 64,
        "timestamp": "2026-11-01T00:00:00+00:00",
        "failure_code": "NONE",
        "psp_id": "PSP_GPAY",
        "extra_drifted_col": 123,
    }
    ok, reasons = validate_event(bad_event, contract)
    assert not ok
    joined = " ".join(reasons)
    assert "NULL_KEY" in joined
    assert "SEMANTIC_ENUM" in joined
    assert "SEMANTIC_RANGE" in joined
    assert "PII_EXPOSURE" in joined
    assert "SCHEMA_DRIFT" in joined


@pytest.mark.unit
def test_breaking_change_detection(tmp_path: Path) -> None:
    old_c = load_contract("psp")
    new_c = copy.deepcopy(old_c)
    # Remove a field -> breaking
    new_c["schema"] = [f for f in new_c["schema"] if f["name"] != "psp_id"]

    breaks = check_breaking_change(old_c, new_c)
    assert any("Removed field 'psp_id'" in b for b in breaks)

    # Blocked without major bump + ADR
    allowed, _ = is_breaking_allowed(old_c, new_c, tmp_path)
    assert not allowed

    # Allowed when major version bumped AND ADR exists
    new_c["version"] = "2.0.0"
    (tmp_path / "ADR-0002-test.md").write_text("# ADR", encoding="utf-8")
    allowed2, _ = is_breaking_allowed(old_c, new_c, tmp_path)
    assert allowed2
