# ReconLake Benchmarks

Measured end-to-end on the local development machine using `scripts/benchmark.py` (seeded synthetic UPI data with `defect_profile="medium"` and `fraud_profile="standard"`).

## Machine Specification

- **OS / Platform**: `Windows-10-10.0.26300-SP0`
- **Python**: `3.11.14`
- **CPU**: `Intel64 Family 6 Model 154 Stepping 4, GenuineIntel` (`12` logical cores)

## Measured Throughput, Latency & Memory

| Canonical Txns | Total Ledger Events | Generator (s) | Bronze (s) | Silver (s) | Recon (s) | Total E2E (s) | E2E Throughput (events/s) | Peak RSS (MB) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **10,000** | 30,500 | 0.797 | 4.855 | 4.843 | 1.032 | 11.527 | 2,645.9 | 232.57 |
| **100,000** | 304,981 | 8.549 | 46.254 | 45.749 | 9.436 | 109.987 | 2,772.9 | 1,206.45 |

## Honest Limits & Scaling Notes

1. **Single-process Python/PyArrow mode**: Scales linearly at **~2,700 events/s E2E** (~1.2 GB peak RSS at 100k txns / 305k ledger events), comfortably inside an **8 GB RAM** laptop budget.
2. **Bottleneck**: Per-row JSONSchema validation in Bronze and Silver (`~46s` each at 305k events) dominates latency; batching via PySpark/JVM (`infra/docker-compose.yml` `streaming` profile) is required for 1M–5M event runs without hitting multi-minute single-process Python loops.
3. **O(N) Fuzzy Reconciliation**: Indexing unmatched bank entries by `(payer_vpa_token, payee_vpa_token, amount_paise)` reduced 100k-txn reconciliation to `9.436s`.
