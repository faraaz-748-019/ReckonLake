"""
Great Expectations-aligned expectation suite evaluator for Silver UPI ledger tables.
Executes declarative expectations per table without requiring heavy external GX context setup,
and mirrors Great Expectations Core assertion semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TOKEN_RE = re.compile(r"^[a-f0-9]{64}$")
VALID_STATES = {"INITIATED", "DEBIT_OK", "CREDIT_OK", "SUCCESS", "FAILED", "PENDING", "REVERSED"}
VALID_TYPES = {"P2P", "P2M", "COLLECT"}

EVENT_ID_KEY = {
    "psp": "psp_event_id",
    "payer_bank": "bank_event_id",
    "switch": "switch_event_id",
}


@dataclass
class ExpectationResult:
    expectation_type: str
    column: str
    success: bool
    unexpected_count: int
    total_count: int


def run_silver_expectations(records: list[dict[str, Any]], source: str) -> dict[str, Any]:
    """Run column and semantic expectations on cleansed Silver records."""
    id_col = EVENT_ID_KEY[source]
    total = len(records)
    if total == 0:
        return {"success": True, "total": 0, "results": []}

    results: list[ExpectationResult] = []

    # 1. Not null checks
    for col in (id_col, "shared_ref", "amount_paise", "payer_vpa_token", "payee_vpa_token", "timestamp_utc"):
        bad = sum(1 for r in records if r.get(col) is None)
        results.append(ExpectationResult("expect_column_values_to_not_be_null", col, bad == 0, bad, total))

    # 2. Uniqueness of event_id
    seen_ids: set[str] = set()
    dups = 0
    for r in records:
        eid = str(r.get(id_col, ""))
        if eid in seen_ids:
            dups += 1
        seen_ids.add(eid)
    results.append(ExpectationResult("expect_column_values_to_be_unique", id_col, dups == 0, dups, total))

    # 3. Positive integer amount_paise
    bad_amt = sum(1 for r in records if not isinstance(r.get("amount_paise"), int) or r["amount_paise"] <= 0)
    results.append(
        ExpectationResult("expect_column_values_to_be_between", "amount_paise", bad_amt == 0, bad_amt, total)
    )

    # 4. Valid state & type sets
    bad_state = sum(1 for r in records if r.get("state") not in VALID_STATES)
    results.append(ExpectationResult("expect_column_values_to_be_in_set", "state", bad_state == 0, bad_state, total))

    bad_type = sum(1 for r in records if r.get("type") not in VALID_TYPES)
    results.append(ExpectationResult("expect_column_values_to_be_in_set", "type", bad_type == 0, bad_type, total))

    # 5. Tokenised VPA format (64-hex)
    bad_vpa = sum(
        1
        for r in records
        if not TOKEN_RE.match(str(r.get("payer_vpa_token", "")))
        or not TOKEN_RE.match(str(r.get("payee_vpa_token", "")))
    )
    results.append(
        ExpectationResult("expect_column_values_to_match_regex", "payer_vpa_token", bad_vpa == 0, bad_vpa, total)
    )

    all_ok = all(res.success for res in results)
    return {
        "success": all_ok,
        "total": total,
        "passed_expectations": sum(1 for r in results if r.success),
        "failed_expectations": sum(1 for r in results if not r.success),
        "results": [r.__dict__ for r in results],
    }
