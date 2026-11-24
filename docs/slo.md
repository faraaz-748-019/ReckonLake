# Service Level Objectives (SLOs)

| SLO | Metric | Target | Measurement Window | Alert Rule |
|---|---|---|---|---|
| **Ingestion Freshness** | `reconlake_stream_lag_seconds` (p95) | `< 120s` (Bronze), `< 15m` (Silver) | Rolling 15 minutes | `StreamLagHigh` |
| **Data Quality Score** | `reconlake_dq_score` per source & batch | `>= 0.90` | Per hourly/daily batch | `DQScoreBelowThreshold` (halts Gold via circuit breaker) |
| **Reconciliation Completeness** | `(matched + broken_refs) / total_unique_refs` | `100.0%` | Every daily recon run | Conservation assertion + dbt `test_recon_totals.sql` |
| **Audit Chain Integrity** | `reconlake_audit_chain_valid` | `1` (100% valid) | Continuous / per check | `AuditChainVerificationFailure` |
