# Reconciliation Precision & Recall Results

Measured by `scripts/benchmark.py` against generator ground-truth defect labels (`defect_profile="medium"`, `seed=42`) at **10,000** and **100,000** canonical transactions.

## 100,000 Transactions (304,981 Ledger Events)

| Break Category | Ground Truth | Detected | True Positives | Precision | Recall | Notes |
|---|---:|---:|---:|---:|---:|---|
| `AMOUNT_MISMATCH` | 990 | 919 | 919 | **1.0000** | **0.9283** | 71 missed refs were co-injected with `NULL_KEY`/`WRONG_TYPE` and quarantined upstream |
| `MISSING_IN_BANK` | 311 | 558 | 297 | 0.5323 | **0.9550** | Extra detections stem from `LATE_ARRIVAL` / `SCHEMA_DRIFT` shifts on one leg |
| `MISSING_IN_PSP` | 333 | 577 | 322 | 0.5581 | **0.9670** | Same cross-defect quarantine interaction |
| `MISSING_IN_SWITCH` | 356 | 597 | 346 | 0.5796 | **0.9719** | Same cross-defect quarantine interaction |
| `TIMING_BREAK` | 3,024 | 6,808 | 2,801 | 0.4114 | **0.9263** | `LATE_ARRIVAL` (1–48h backdate) also creates >300s cross-ledger delta, truthfully flagged as timing break |
| `DUPLICATE` (post-Silver) | 5,853 | 0 | 0 | — | — | 100% of exact duplicate `event_id`s are removed by Silver deduplication prior to reconciliation; direct Recon unit tests (`test_recon.py`) verify 100% duplicate break detection on un-deduplicated feeds |

## 10,000 Transactions (30,500 Ledger Events)

| Break Category | Ground Truth | Detected | True Positives | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| `AMOUNT_MISMATCH` | 99 | 95 | 95 | **1.0000** | **0.9596** |
| `MISSING_IN_BANK` | 36 | 54 | 36 | 0.6667 | **1.0000** |
| `MISSING_IN_PSP` | 35 | 57 | 35 | 0.6140 | **1.0000** |
| `MISSING_IN_SWITCH` | 29 | 45 | 25 | 0.5556 | **0.8621** |
| `TIMING_BREAK` | 305 | 681 | 278 | 0.4082 | **0.9115** |
