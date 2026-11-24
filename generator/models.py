"""
Pydantic models and dataclasses for the ReconLake UPI generator.

Enums
-----
TransactionType   : P2P | P2M | COLLECT
TransactionState  : INITIATED → DEBIT_OK → CREDIT_OK → SUCCESS
                                           ↘ FAILED
                                 ↘ PENDING → SUCCESS | FAILED
                    Any SUCCESS/FAILED → REVERSED
FailureCode       : reason codes mirroring NPCI's list
BreakCategory     : reconciliation break types

Models
------
Customer, Merchant        : participant master data (tokenised)
Transaction               : canonical transaction record
PSPEvent                  : PSP's view of the transaction
PayerBankEvent            : Payer bank's view
SwitchEvent               : NPCI switch's view
FraudLabel / DefectLabel  : ground-truth annotation dataclasses
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TransactionType(str, Enum):
    P2P = "P2P"
    P2M = "P2M"
    COLLECT = "COLLECT"


class TransactionState(str, Enum):
    INITIATED = "INITIATED"
    DEBIT_OK = "DEBIT_OK"
    CREDIT_OK = "CREDIT_OK"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


class FailureCode(str, Enum):
    NONE = "NONE"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INVALID_VPA = "INVALID_VPA"
    BANK_DECLINE = "BANK_DECLINE"
    TIMEOUT = "TIMEOUT"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"
    EXCEED_LIMIT = "EXCEED_LIMIT"
    WRONG_PIN = "WRONG_PIN"
    EXPIRED_CARD = "EXPIRED_CARD"
    ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"


class BreakCategory(str, Enum):
    # Reconciliation break categories
    MISSING_IN_PSP = "MISSING_IN_PSP"
    MISSING_IN_PAYER_BANK = "MISSING_IN_PAYER_BANK"
    MISSING_IN_SWITCH = "MISSING_IN_SWITCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STATE_MISMATCH = "STATE_MISMATCH"
    TIMESTAMP_SKEW = "TIMESTAMP_SKEW"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    LATE_ARRIVAL = "LATE_ARRIVAL"
    NULL_KEY = "NULL_KEY"
    WRONG_TYPE = "WRONG_TYPE"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"


# ---------------------------------------------------------------------------
# Master data models
# ---------------------------------------------------------------------------


class Customer(BaseModel):
    """Tokenised customer master record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name_token: str  # SHA-256 token of real name
    vpa: str  # e.g. user1234@okaxis
    phone_token: str  # SHA-256 token of phone number
    account_token: str  # SHA-256 token of account number
    bank_id: str  # e.g. AXIS, HDFC, SBI
    device_id: str  # unique device fingerprint


class Merchant(BaseModel):
    """Merchant master record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    mcc_code: str  # ISO 18245 MCC
    vpa: str  # e.g. merchant@icici
    bank_id: str


# ---------------------------------------------------------------------------
# Transaction canonical model
# ---------------------------------------------------------------------------


class Transaction(BaseModel):
    """
    Canonical UPI transaction record.
    ``shared_ref`` is the correlation key across all three ledgers.
    """

    txn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shared_ref: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: TransactionType
    state: TransactionState
    amount_paise: int = Field(ge=1)  # smallest unit; 100 paise = ₹1
    payer_vpa_token: str
    payee_vpa_token: str
    timestamp: datetime
    failure_code: FailureCode = FailureCode.NONE
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-ledger event models
# ---------------------------------------------------------------------------


class PSPEvent(BaseModel):
    """
    PSP (Payment Service Provider / app) ledger record.
    Contains the PSP's local event id plus a small timestamp jitter
    reflecting network propagation delay.
    """

    psp_event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shared_ref: str
    txn_id: str
    type: TransactionType
    state: TransactionState
    amount_paise: int
    payer_vpa_token: str
    payee_vpa_token: str
    timestamp: datetime  # PSP's wall-clock (may differ from canonical by ±jitter)
    failure_code: FailureCode = FailureCode.NONE
    psp_id: str = "PSP_01"
    extra: dict[str, Any] = Field(default_factory=dict)


class PayerBankEvent(BaseModel):
    """
    Payer bank's core-banking ledger record.
    Has its own event id and a distinct timestamp (CBS processing lag).
    """

    bank_event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shared_ref: str
    txn_id: str
    type: TransactionType
    state: TransactionState
    amount_paise: int
    payer_vpa_token: str
    payee_vpa_token: str
    timestamp: datetime
    failure_code: FailureCode = FailureCode.NONE
    bank_id: str = "BANK_01"
    debit_reference: str = Field(default_factory=lambda: str(uuid.uuid4()))
    extra: dict[str, Any] = Field(default_factory=dict)


class SwitchEvent(BaseModel):
    """
    NPCI switch ledger record.
    Central switch sees both legs; has its own event id.
    """

    switch_event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shared_ref: str
    txn_id: str
    type: TransactionType
    state: TransactionState
    amount_paise: int
    payer_vpa_token: str
    payee_vpa_token: str
    timestamp: datetime
    failure_code: FailureCode = FailureCode.NONE
    rrn: str = Field(default_factory=lambda: str(uuid.uuid4())[:12].upper())
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ground-truth annotation dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FraudLabel:
    """Ground-truth fraud annotation for a transaction."""

    shared_ref: str
    typology: str  # e.g. "mule_ring", "velocity_burst"
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DefectLabel:
    """Ground-truth data-quality defect annotation for an event."""

    event_id: str  # the per-ledger event id (psp_event_id / bank_event_id / switch_event_id)
    shared_ref: str
    ledger: str  # "psp" | "payer_bank" | "switch"
    defect_type: BreakCategory
    details: dict[str, Any] = field(default_factory=dict)
