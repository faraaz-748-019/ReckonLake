"""
Seeded, reproducible synthetic UPI lifecycle generator for ReconLake.

Generates multi-party UPI payment lifecycles across three independent ledgers:
  - psp_ledger (PSP app view)
  - payer_bank_ledger (CBS view)
  - switch_ledger (NPCI switch view)

Every transaction transitions cleanly along valid state-machine edges and emits
ledger events linked by a shared reference number (`shared_ref`).
Fraud typologies and data-quality defects are injected with configurable rates
and logged to separate ground-truth JSONL files for downstream evaluation.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import uuid
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from generator.defects import (
    inject_amount_mismatch,
    inject_clock_skew,
    inject_duplicates,
    inject_late_events,
    inject_missing_ledger_entry,
    inject_null_keys,
    inject_schema_drift,
    inject_wrong_types,
)
from generator.fraud import (
    collect_request_scams,
    device_sharing,
    mule_rings,
    round_amount_structuring,
    velocity_bursts,
)
from generator.models import (
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

# ---------------------------------------------------------------------------
# Valid UPI lifecycle state machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.INITIATED: frozenset(
        {TransactionState.DEBIT_OK, TransactionState.FAILED, TransactionState.PENDING}
    ),
    TransactionState.DEBIT_OK: frozenset(
        {TransactionState.CREDIT_OK, TransactionState.FAILED, TransactionState.PENDING, TransactionState.REVERSED}
    ),
    TransactionState.CREDIT_OK: frozenset(
        {TransactionState.SUCCESS, TransactionState.REVERSED}
    ),
    TransactionState.PENDING: frozenset(
        {TransactionState.SUCCESS, TransactionState.FAILED, TransactionState.REVERSED}
    ),
    TransactionState.SUCCESS: frozenset({TransactionState.REVERSED}),
    TransactionState.FAILED: frozenset({TransactionState.REVERSED}),
    TransactionState.REVERSED: frozenset(),
}

DEFECT_PROFILES: dict[str, dict[str, float]] = {
    "none": {
        "duplicate": 0.0,
        "late": 0.0,
        "null_key": 0.0,
        "wrong_type": 0.0,
        "schema_drift": 0.0,
        "clock_skew": 0.0,
        "missing_ledger": 0.0,
        "amount_mismatch": 0.0,
    },
    "low": {
        "duplicate": 0.005,
        "late": 0.005,
        "null_key": 0.002,
        "wrong_type": 0.002,
        "schema_drift": 0.002,
        "clock_skew": 0.003,
        "missing_ledger": 0.003,
        "amount_mismatch": 0.002,
    },
    "medium": {
        "duplicate": 0.02,
        "late": 0.015,
        "null_key": 0.01,
        "wrong_type": 0.005,
        "schema_drift": 0.005,
        "clock_skew": 0.01,
        "missing_ledger": 0.01,
        "amount_mismatch": 0.01,
    },
    "high": {
        "duplicate": 0.05,
        "late": 0.04,
        "null_key": 0.03,
        "wrong_type": 0.02,
        "schema_drift": 0.02,
        "clock_skew": 0.03,
        "missing_ledger": 0.03,
        "amount_mismatch": 0.03,
    },
}

FRAUD_PROFILES: dict[str, dict[str, int]] = {
    "none": {"rings": 0, "bursts": 0, "scammers": 0, "structured": 0, "devices": 0},
    "standard": {"rings": 3, "bursts": 5, "scammers": 4, "structured": 20, "devices": 3},
    "heavy": {"rings": 10, "bursts": 15, "scammers": 12, "structured": 60, "devices": 8},
}

PSP_HANDLES = ["okaxis", "okicici", "oksbi", "okhdfcbank", "ybl", "paytm"]
PSP_APPS = ["PSP_GPAY", "PSP_PHONEPE", "PSP_PAYTM", "PSP_BHIM", "PSP_CRED"]
BANK_IDS = ["AXIS", "HDFC", "SBI", "ICICI", "KOTAK", "YESB"]
MCC_CODES = ["5411", "5812", "5999", "4121", "4814", "5912"]
FAILURE_CODES = [
    FailureCode.INSUFFICIENT_FUNDS,
    FailureCode.INVALID_VPA,
    FailureCode.BANK_DECLINE,
    FailureCode.TIMEOUT,
    FailureCode.TECHNICAL_ERROR,
    FailureCode.EXCEED_LIMIT,
    FailureCode.WRONG_PIN,
]


def _det_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _det_token(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def is_valid_transition(src: TransactionState, dst: TransactionState) -> bool:
    """Return True if transitioning from *src* to *dst* obeys the UPI state machine."""
    return dst in VALID_TRANSITIONS[src]


def simulate_lifecycle(rng: random.Random) -> tuple[list[TransactionState], FailureCode]:
    """
    Walk the UPI state machine from INITIATED to a terminal or resting state.
    Guarantees every transition is legal in VALID_TRANSITIONS.
    """
    path: list[TransactionState] = [TransactionState.INITIATED]
    current = TransactionState.INITIATED
    failure = FailureCode.NONE

    roll = rng.random()
    if roll < 0.04:
        # Early failure at initiation
        nxt = TransactionState.FAILED
        assert is_valid_transition(current, nxt)
        path.append(nxt)
        return path, rng.choice(FAILURE_CODES)

    if roll < 0.08:
        # Pending -> resolve
        nxt = TransactionState.PENDING
        assert is_valid_transition(current, nxt)
        path.append(nxt)
        current = nxt
        final = TransactionState.SUCCESS if rng.random() < 0.65 else TransactionState.FAILED
        assert is_valid_transition(current, final)
        path.append(final)
        if final == TransactionState.FAILED:
            failure = rng.choice(FAILURE_CODES)
        return path, failure

    # Normal happy-ish path: INITIATED -> DEBIT_OK
    nxt = TransactionState.DEBIT_OK
    assert is_valid_transition(current, nxt)
    path.append(nxt)
    current = nxt

    if rng.random() < 0.05:
        # Debit OK but credit fails -> FAILED or REVERSED
        nxt = TransactionState.FAILED
        assert is_valid_transition(current, nxt)
        path.append(nxt)
        current = nxt
        failure = FailureCode.TIMEOUT
        if rng.random() < 0.7:
            rev = TransactionState.REVERSED
            assert is_valid_transition(current, rev)
            path.append(rev)
        return path, failure

    nxt = TransactionState.CREDIT_OK
    assert is_valid_transition(current, nxt)
    path.append(nxt)
    current = nxt

    nxt = TransactionState.SUCCESS
    assert is_valid_transition(current, nxt)
    path.append(nxt)
    current = nxt

    # Occasional post-success reversal / refund
    if rng.random() < 0.01:
        rev = TransactionState.REVERSED
        assert is_valid_transition(current, rev)
        path.append(rev)

    return path, failure


class UPIGenerator:
    """Seeded, reproducible synthetic UPI transaction & multi-ledger generator."""

    def __init__(
        self,
        seed: int = 42,
        count: int = 10_000,
        rate: int = 1000,
        defect_profile: str = "medium",
        fraud_profile: str = "standard",
        batch_size: int = 5000,
        base_time: datetime | None = None,
    ) -> None:
        if defect_profile not in DEFECT_PROFILES:
            raise ValueError(f"Unknown defect_profile: {defect_profile}")
        if fraud_profile not in FRAUD_PROFILES:
            raise ValueError(f"Unknown fraud_profile: {fraud_profile}")
        self.seed = seed
        self.count = count
        self.rate = rate
        self.defect_profile = defect_profile
        self.fraud_profile = fraud_profile
        self.batch_size = max(1, batch_size)
        self.rng = random.Random(seed)
        self.base_time = base_time or datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC)

        self.customers = self._build_customers(max(50, min(2000, count // 10 + 50)))
        self.merchants = self._build_merchants(max(20, min(500, count // 50 + 20)))

    def _build_customers(self, n: int) -> list[Customer]:
        customers: list[Customer] = []
        for i in range(n):
            handle = self.rng.choice(PSP_HANDLES)
            vpa = f"cust{i:05d}@{handle}"
            customers.append(
                Customer(
                    id=_det_uuid(self.rng),
                    name_token=_det_token(f"CustName{i}", "name"),
                    vpa=vpa,
                    phone_token=_det_token(f"+9198{i:08d}", "phone"),
                    account_token=_det_token(f"ACCT{i:012d}", "account"),
                    bank_id=self.rng.choice(BANK_IDS),
                    device_id=f"DEV_{self.rng.getrandbits(32):08X}",
                )
            )
        return customers

    def _build_merchants(self, n: int) -> list[Merchant]:
        merchants: list[Merchant] = []
        for i in range(n):
            handle = self.rng.choice(PSP_HANDLES)
            merchants.append(
                Merchant(
                    id=_det_uuid(self.rng),
                    name=f"SynthMerchant_{i:04d}",
                    mcc_code=self.rng.choice(MCC_CODES),
                    vpa=f"merchant{i:04d}@{handle}",
                    bank_id=self.rng.choice(BANK_IDS),
                )
            )
        return merchants

    def _make_transactions(self, n: int, offset_seconds: int = 0) -> list[Transaction]:
        txns: list[Transaction] = []
        for i in range(n):
            payer = self.rng.choice(self.customers)
            txn_type = self.rng.choices(
                [TransactionType.P2P, TransactionType.P2M, TransactionType.COLLECT],
                weights=[0.50, 0.40, 0.10],
            )[0]
            if txn_type == TransactionType.P2M:
                payee_vpa = self.rng.choice(self.merchants).vpa
            else:
                payee = self.rng.choice(self.customers)
                payee_vpa = payee.vpa

            path, failure_code = simulate_lifecycle(self.rng)
            final_state = path[-1]
            # Log-normal-like realistic UPI amounts in paise (₹1 to ₹50,000)
            amount_rupees = int(min(50_000, max(1, round(self.rng.expovariate(1 / 850)))))
            amount_paise = amount_rupees * 100
            ts = self.base_time + timedelta(
                seconds=offset_seconds + (i * 86400) // max(1, n),
                milliseconds=self.rng.randint(0, 999),
            )
            txns.append(
                Transaction(
                    txn_id=_det_uuid(self.rng),
                    shared_ref=f"UPI{self.rng.getrandbits(64):016X}",
                    type=txn_type,
                    state=final_state,
                    amount_paise=amount_paise,
                    payer_vpa_token=_det_token(payer.vpa, "vpa"),
                    payee_vpa_token=_det_token(payee_vpa, "vpa"),
                    timestamp=ts,
                    failure_code=failure_code,
                    metadata={
                        "payer_bank_id": payer.bank_id,
                        "device_id": payer.device_id,
                        "lifecycle_path": [s.value for s in path],
                    },
                )
            )
        return txns

    def _to_ledger_events(
        self, txns: list[Transaction]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        psp_events: list[dict[str, Any]] = []
        bank_events: list[dict[str, Any]] = []
        switch_events: list[dict[str, Any]] = []

        for txn in txns:
            psp_ts = txn.timestamp + timedelta(milliseconds=self.rng.randint(0, 150))
            bank_ts = txn.timestamp + timedelta(milliseconds=self.rng.randint(50, 400))
            switch_ts = txn.timestamp + timedelta(milliseconds=self.rng.randint(20, 250))

            psp = PSPEvent(
                psp_event_id=_det_uuid(self.rng),
                shared_ref=txn.shared_ref,
                txn_id=txn.txn_id,
                type=txn.type,
                state=txn.state,
                amount_paise=txn.amount_paise,
                payer_vpa_token=txn.payer_vpa_token,
                payee_vpa_token=txn.payee_vpa_token,
                timestamp=psp_ts,
                failure_code=txn.failure_code,
                psp_id=self.rng.choice(PSP_APPS),
            ).model_dump(mode="json")

            bank = PayerBankEvent(
                bank_event_id=_det_uuid(self.rng),
                shared_ref=txn.shared_ref,
                txn_id=txn.txn_id,
                type=txn.type,
                state=txn.state,
                amount_paise=txn.amount_paise,
                payer_vpa_token=txn.payer_vpa_token,
                payee_vpa_token=txn.payee_vpa_token,
                timestamp=bank_ts,
                failure_code=txn.failure_code,
                bank_id=txn.metadata.get("payer_bank_id", "AXIS"),
                debit_reference=f"CBS{self.rng.getrandbits(48):012X}",
            ).model_dump(mode="json")

            switch = SwitchEvent(
                switch_event_id=_det_uuid(self.rng),
                shared_ref=txn.shared_ref,
                txn_id=txn.txn_id,
                type=txn.type,
                state=txn.state,
                amount_paise=txn.amount_paise,
                payer_vpa_token=txn.payer_vpa_token,
                payee_vpa_token=txn.payee_vpa_token,
                timestamp=switch_ts,
                failure_code=txn.failure_code,
                rrn=f"{self.rng.getrandbits(48):012X}",
            ).model_dump(mode="json")

            psp_events.append(psp)
            bank_events.append(bank)
            switch_events.append(switch)

        return psp_events, bank_events, switch_events

    def generate(
        self,
    ) -> Iterator[
        tuple[
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[FraudLabel],
            list[DefectLabel],
        ]
    ]:
        """Yield batches of (psp_events, bank_events, switch_events, fraud_labels, defect_labels)."""
        f_cfg = FRAUD_PROFILES[self.fraud_profile]
        d_cfg = DEFECT_PROFILES[self.defect_profile]

        remaining = self.count
        batch_idx = 0
        while remaining > 0:
            cur_n = min(self.batch_size, remaining)
            txns = self._make_transactions(cur_n, offset_seconds=batch_idx * 86400)

            fraud_labels: list[FraudLabel] = []
            if any(f_cfg.values()):
                txns, l1 = mule_rings(txns, self.rng, num_rings=f_cfg["rings"], payers_per_ring=10)
                txns, l2 = velocity_bursts(txns, self.rng, num_bursts=f_cfg["bursts"], txns_per_burst=15)
                txns, l3 = collect_request_scams(txns, self.rng, num_scammers=f_cfg["scammers"], requests_per_scammer=8)
                txns, l4 = round_amount_structuring(txns, self.rng, num_structured=f_cfg["structured"])
                txns, l5 = device_sharing(txns, self.rng, self.customers, num_shared_devices=f_cfg["devices"])
                # Ensure tokens stay 64-char hex even when fraud injectors assign raw mule/scam VPAs
                for t in txns:
                    if len(t.payee_vpa_token) != 64:
                        t.payee_vpa_token = _det_token(t.payee_vpa_token, "vpa")
                fraud_labels.extend([*l1, *l2, *l3, *l4, *l5])

            psp_ev, bank_ev, switch_ev = self._to_ledger_events(txns)
            defect_labels: list[DefectLabel] = []

            # Cross-ledger defects first (on clean refs)
            if d_cfg["missing_ledger"] > 0:
                psp_ev, bank_ev, switch_ev, dl = inject_missing_ledger_entry(
                    psp_ev, bank_ev, switch_ev, d_cfg["missing_ledger"], self.rng
                )
                defect_labels.extend(dl)

            if d_cfg["amount_mismatch"] > 0:
                psp_ev, bank_ev, switch_ev, dl = inject_amount_mismatch(
                    psp_ev, bank_ev, switch_ev, d_cfg["amount_mismatch"], self.rng
                )
                defect_labels.extend(dl)

            # Per-ledger defects
            for ledger_events in (psp_ev, bank_ev, switch_ev):
                if d_cfg["duplicate"] > 0:
                    updated, dl = inject_duplicates(ledger_events, d_cfg["duplicate"], self.rng)
                    ledger_events[:] = updated
                    defect_labels.extend(dl)
                if d_cfg["late"] > 0:
                    updated, dl = inject_late_events(ledger_events, d_cfg["late"], self.rng)
                    ledger_events[:] = updated
                    defect_labels.extend(dl)
                if d_cfg["clock_skew"] > 0:
                    updated, dl = inject_clock_skew(ledger_events, d_cfg["clock_skew"], self.rng)
                    ledger_events[:] = updated
                    defect_labels.extend(dl)
                if d_cfg["null_key"] > 0:
                    updated, dl = inject_null_keys(ledger_events, d_cfg["null_key"], self.rng)
                    ledger_events[:] = updated
                    defect_labels.extend(dl)
                if d_cfg["wrong_type"] > 0:
                    updated, dl = inject_wrong_types(ledger_events, d_cfg["wrong_type"], self.rng)
                    ledger_events[:] = updated
                    defect_labels.extend(dl)
                if d_cfg["schema_drift"] > 0:
                    updated, dl = inject_schema_drift(ledger_events, d_cfg["schema_drift"], self.rng)
                    ledger_events[:] = updated
                    defect_labels.extend(dl)

            yield psp_ev, bank_ev, switch_ev, fraud_labels, defect_labels
            remaining -= cur_n
            batch_idx += 1

    def write_files(self, output_dir: str | Path, file_format: str = "jsonl") -> dict[str, Any]:
        """Generate all events and write to disk (JSONL and/or Parquet) + ground-truth files."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        gt_dir = out / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        counts = {"psp": 0, "payer_bank": 0, "switch": 0, "fraud_labels": 0, "defect_labels": 0}

        psp_path = out / "psp_ledger.jsonl"
        bank_path = out / "payer_bank_ledger.jsonl"
        switch_path = out / "switch_ledger.jsonl"
        fraud_path = gt_dir / "fraud_labels.jsonl"
        defect_path = gt_dir / "defect_labels.jsonl"

        all_psp: list[dict[str, Any]] = []
        all_bank: list[dict[str, Any]] = []
        all_switch: list[dict[str, Any]] = []

        with (
            psp_path.open("w", encoding="utf-8") as f_psp,
            bank_path.open("w", encoding="utf-8") as f_bank,
            switch_path.open("w", encoding="utf-8") as f_sw,
            fraud_path.open("w", encoding="utf-8") as f_fr,
            defect_path.open("w", encoding="utf-8") as f_df,
        ):
            for psp_ev, bank_ev, switch_ev, fraud_lbl, defect_lbl in self.generate():
                for row in psp_ev:
                    f_psp.write(json.dumps(row, default=str) + "\n")
                for row in bank_ev:
                    f_bank.write(json.dumps(row, default=str) + "\n")
                for row in switch_ev:
                    f_sw.write(json.dumps(row, default=str) + "\n")
                for fl in fraud_lbl:
                    f_fr.write(json.dumps(asdict(fl), default=str) + "\n")
                for dl in defect_lbl:
                    rec = asdict(dl)
                    rec["defect_type"] = dl.defect_type.value
                    f_df.write(json.dumps(rec, default=str) + "\n")

                counts["psp"] += len(psp_ev)
                counts["payer_bank"] += len(bank_ev)
                counts["switch"] += len(switch_ev)
                counts["fraud_labels"] += len(fraud_lbl)
                counts["defect_labels"] += len(defect_lbl)

                if file_format in ("parquet", "both"):
                    all_psp.extend(psp_ev)
                    all_bank.extend(bank_ev)
                    all_switch.extend(switch_ev)

        if file_format in ("parquet", "both"):
            for name, rows in [("psp_ledger", all_psp), ("payer_bank_ledger", all_bank), ("switch_ledger", all_switch)]:
                if rows:
                    # Coerce heterogeneous defect-injected values to string for Parquet safety
                    norm_rows = [
                        {
                            k: json.dumps(v) if isinstance(v, dict | list) else (str(v) if v is not None else None)
                            for k, v in r.items()
                        }
                        for r in rows
                    ]
                    table = pa.Table.from_pylist(norm_rows)
                    pq.write_table(table, out / f"{name}.parquet")

        elapsed = max(1e-6, time.perf_counter() - t0)
        total_events = counts["psp"] + counts["payer_bank"] + counts["switch"]
        return {
            "total_transactions": self.count,
            "total_ledger_events": total_events,
            "counts": counts,
            "elapsed_seconds": round(elapsed, 3),
            "throughput_events_per_sec": round(total_events / elapsed, 1),
            "output_dir": str(out),
        }

    def produce_kafka(self, bootstrap_servers: str | None = None) -> dict[str, Any]:
        """Publish generated ledger events to Kafka topics (psp_ledger, payer_bank_ledger, switch_ledger)."""
        from kafka import KafkaProducer  # lazy import so file mode doesn't require kafka-python at runtime

        brokers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
        producer = KafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        t0 = time.perf_counter()
        total = 0
        try:
            for psp_ev, bank_ev, switch_ev, _, _ in self.generate():
                for topic, batch in [
                    ("psp_ledger", psp_ev),
                    ("payer_bank_ledger", bank_ev),
                    ("switch_ledger", switch_ev),
                ]:
                    for ev in batch:
                        key = ev.get("shared_ref") or ""
                        producer.send(topic, key=key, value=ev)
                        total += 1
            producer.flush()
        finally:
            producer.close()
        elapsed = max(1e-6, time.perf_counter() - t0)
        return {
            "total_ledger_events": total,
            "elapsed_seconds": round(elapsed, 3),
            "throughput_events_per_sec": round(total / elapsed, 1),
        }
