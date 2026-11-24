"""
Fraud typology injector for the ReconLake UPI generator.

Each function accepts a list of Transaction objects (or mutable dicts)
and a random.Random instance for reproducibility, marks specific
transactions as fraudulent, and returns the modified transactions plus
a list of FraudLabel ground-truth annotations.

Typologies implemented
----------------------
mule_rings              Fan-in: many payers → one mule VPA
velocity_bursts         Single payer rapid-fires many transactions
collect_request_scams   Phishing collect requests from suspicious payees
round_amount_structuring  Amounts just below ₹2 lakh reporting threshold
device_sharing          Same device_id registered across multiple customers
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from generator.models import (
    FailureCode,
    FraudLabel,
    Transaction,
    TransactionState,
    TransactionType,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_mule_vpa(rng: random.Random) -> str:
    return f"mule{rng.getrandbits(24):06x}@ybl"


def _flag(txn: Transaction, typology: str, **details: Any) -> FraudLabel:
    return FraudLabel(
        shared_ref=txn.shared_ref,
        typology=typology,
        confidence=1.0,
        details=details,
    )


# ---------------------------------------------------------------------------
# Typology functions
# ---------------------------------------------------------------------------


def mule_rings(
    transactions: list[Transaction],
    rng: random.Random,
    *,
    num_rings: int = 3,
    payers_per_ring: int = 10,
) -> tuple[list[Transaction], list[FraudLabel]]:
    """
    Inject fan-in mule ring patterns.

    For each ring we:
      1. Pick (or create) a mule payee VPA.
      2. Force ``payers_per_ring`` transactions to route to that mule.
      3. Set state to SUCCESS so the debit cleared.

    Returns the modified transaction list and ground-truth FraudLabels.
    """
    labels: list[FraudLabel] = []
    if not transactions:
        return transactions, labels

    for ring_idx in range(num_rings):
        mule_vpa = _make_mule_vpa(rng)
        # pick victims from the transaction pool
        pool = rng.sample(
            range(len(transactions)),
            k=min(payers_per_ring, len(transactions)),
        )
        for idx in pool:
            txn = transactions[idx]
            # Redirect to mule
            txn.payee_vpa_token = mule_vpa
            txn.state = TransactionState.SUCCESS
            txn.failure_code = FailureCode.NONE
            txn.metadata["fraud_ring_id"] = f"ring_{ring_idx}"
            labels.append(
                _flag(
                    txn,
                    "mule_ring",
                    ring_id=f"ring_{ring_idx}",
                    mule_vpa=mule_vpa,
                )
            )

    return transactions, labels


def velocity_bursts(
    transactions: list[Transaction],
    rng: random.Random,
    *,
    num_bursts: int = 5,
    txns_per_burst: int = 15,
    burst_window_seconds: int = 60,
) -> tuple[list[Transaction], list[FraudLabel]]:
    """
    Inject velocity-burst patterns: one payer fires many transactions
    within a short window.

    We pick a random payer VPA token and compress a cluster of transactions
    into a tight time window.
    """
    labels: list[FraudLabel] = []
    if len(transactions) < txns_per_burst:
        return transactions, labels

    payer_vpas = list({txn.payer_vpa_token for txn in transactions})

    for burst_idx in range(min(num_bursts, len(payer_vpas))):
        burst_payer = rng.choice(payer_vpas)
        candidates = [i for i, t in enumerate(transactions) if t.payer_vpa_token == burst_payer]
        if len(candidates) < 2:
            continue
        chosen = rng.sample(candidates, k=min(txns_per_burst, len(candidates)))
        base_ts = transactions[chosen[0]].timestamp
        for rank, idx in enumerate(chosen):
            txn = transactions[idx]
            # compress timestamps into burst window
            txn.timestamp = base_ts + timedelta(seconds=rank * (burst_window_seconds / max(len(chosen), 1)))
            txn.metadata["fraud_burst_id"] = f"burst_{burst_idx}"
            labels.append(
                _flag(
                    txn,
                    "velocity_burst",
                    burst_id=f"burst_{burst_idx}",
                    payer_vpa=burst_payer,
                    rank_in_burst=rank,
                )
            )

    return transactions, labels


def collect_request_scams(
    transactions: list[Transaction],
    rng: random.Random,
    *,
    num_scammers: int = 4,
    requests_per_scammer: int = 8,
) -> tuple[list[Transaction], list[FraudLabel]]:
    """
    Inject phishing collect-request scams.

    A suspicious payee VPA sends COLLECT requests; victims have no prior
    relationship with that payee.  We mark those transactions and set
    type=COLLECT.
    """
    labels: list[FraudLabel] = []
    if not transactions:
        return transactions, labels

    for scammer_idx in range(num_scammers):
        scammer_vpa = f"scam{rng.getrandbits(24):06x}@upi"
        pool = rng.sample(
            range(len(transactions)),
            k=min(requests_per_scammer, len(transactions)),
        )
        for idx in pool:
            txn = transactions[idx]
            txn.type = TransactionType.COLLECT
            txn.payee_vpa_token = scammer_vpa
            # collect that succeeded (victim approved)
            if rng.random() < 0.6:
                txn.state = TransactionState.SUCCESS
                txn.failure_code = FailureCode.NONE
            else:
                txn.state = TransactionState.FAILED
                txn.failure_code = FailureCode.FRAUD_SUSPECTED
            txn.metadata["fraud_scammer_id"] = f"scammer_{scammer_idx}"
            labels.append(
                _flag(
                    txn,
                    "collect_request_scam",
                    scammer_id=f"scammer_{scammer_idx}",
                    scammer_vpa=scammer_vpa,
                )
            )

    return transactions, labels


def round_amount_structuring(
    transactions: list[Transaction],
    rng: random.Random,
    *,
    threshold_paise: int = 20_000_00,  # ₹2,00,000 in paise
    num_structured: int = 20,
    undercut_range: tuple[int, int] = (1_00, 500_00),  # INR 1 - 500 below threshold
) -> tuple[list[Transaction], list[FraudLabel]]:
    """
    Set transaction amounts just below the ₹2 lakh reporting threshold.
    This simulates structuring / smurfing behaviour.
    """
    labels: list[FraudLabel] = []
    if not transactions:
        return transactions, labels

    pool = rng.sample(
        range(len(transactions)),
        k=min(num_structured, len(transactions)),
    )
    for idx in pool:
        txn = transactions[idx]
        undercut = rng.randint(*undercut_range)
        txn.amount_paise = threshold_paise - undercut
        txn.state = TransactionState.SUCCESS
        txn.failure_code = FailureCode.NONE
        labels.append(
            _flag(
                txn,
                "round_amount_structuring",
                threshold_paise=threshold_paise,
                undercut_paise=undercut,
                amount_paise=txn.amount_paise,
            )
        )

    return transactions, labels


def device_sharing(
    transactions: list[Transaction],
    rng: random.Random,
    customers: list[Any] | None = None,
    *,
    num_shared_devices: int = 3,
    customers_per_device: int = 5,
) -> tuple[list[Transaction], list[FraudLabel]]:
    """
    Flag transactions where the originating device_id is shared across
    multiple customer accounts (mule SIM swapping, device farms).

    If ``customers`` is provided we mutate their device_ids directly;
    otherwise we embed the shared device id in transaction metadata.
    """
    labels: list[FraudLabel] = []
    if not transactions:
        return transactions, labels

    for dev_idx in range(num_shared_devices):
        shared_device = f"DEV_{rng.getrandbits(32):08X}"
        pool = rng.sample(
            range(len(transactions)),
            k=min(customers_per_device, len(transactions)),
        )
        for rank, idx in enumerate(pool):
            txn = transactions[idx]
            txn.metadata["shared_device_id"] = shared_device
            txn.metadata["device_fraud_group"] = f"devgroup_{dev_idx}"
            labels.append(
                _flag(
                    txn,
                    "device_sharing",
                    shared_device_id=shared_device,
                    group_id=f"devgroup_{dev_idx}",
                    rank_in_group=rank,
                )
            )
        # If customer objects supplied, actually change device_id on master data
        if customers:
            cust_pool = rng.sample(customers, k=min(customers_per_device, len(customers)))
            for c in cust_pool:
                c.device_id = shared_device

    return transactions, labels
