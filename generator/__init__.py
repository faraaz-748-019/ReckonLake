"""
ReconLake UPI Synthetic Data Generator
=======================================
Generates synthetic UPI transaction events across three ledgers:
  - PSP ledger (psp_events)
  - Payer Bank ledger (payer_bank_events)
  - Switch ledger (switch_events)

Each set of events shares a ``shared_ref`` UUID so they can be correlated
during reconciliation. Fraud typologies and data-quality defects are
injected at configurable rates.

Usage (CLI)::

    python -m generator --seed 42 --count 10000 --rate 500 \\
        --defect-profile medium --fraud-profile standard \\
        --mode file --output-dir ./data

Usage (Python)::

    from generator import UPIGenerator

    gen = UPIGenerator(seed=42, count=1000, rate=100,
                       defect_profile="medium", fraud_profile="standard")
    for psp, payer, switch in gen.generate():
        process(psp, payer, switch)
"""

from generator.models import (
    BreakCategory,
    Customer,
    DefectLabel,
    FailureCode,
    FraudLabel,
    Merchant,
    PayerBankEvent,
    PSPEvent,
    SwitchEvent,
    Transaction,
    TransactionState,
    TransactionType,
)
from generator.producer import UPIGenerator

__all__ = [
    "UPIGenerator",
    "Customer",
    "Merchant",
    "Transaction",
    "PSPEvent",
    "PayerBankEvent",
    "SwitchEvent",
    "FraudLabel",
    "DefectLabel",
    "TransactionType",
    "TransactionState",
    "FailureCode",
    "BreakCategory",
]

__version__ = "0.1.0"
