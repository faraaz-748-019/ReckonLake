# ReconLake 5-Minute Live Demo Script

1. **Generate Secrets & Start Core Stack (or run locally)**
   ```bash
   make generate-secrets
   make up PROFILE=core
   ```
2. **Run End-to-End Automated Demo (`make demo`)**
   ```bash
   make demo
   ```
   Show the terminal output:
   - Seeded generation of synthetic UPI events across `psp_ledger`, `payer_bank_ledger`, `switch_ledger` with injected fraud and defects.
   - Contract-enforced Bronze ingestion quarantining `NULL_KEY`, `WRONG_TYPE`, and `SCHEMA_DRIFT` records with reason codes.
   - Silver deduplication, 5-dimension DQ Score calculation, and circuit breaker status.
   - Three-way reconciliation detecting `MISSING_IN_*`, `AMOUNT_MISMATCH`, `TIMING_BREAK`, `DUPLICATE` with precision & recall against ground truth.
   - Crypto-shredding of a customer token DEK (`reconlake-shred`) proving encrypted PII is permanently unrecoverable while Gold KPIs remain intact.
   - Hash-chained audit log verification (`reconlake-verify-audit`) returning `valid: true`.
3. **Verify Tests & Security Scans**
   ```bash
   make test
   make security
   ```
