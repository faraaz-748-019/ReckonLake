# ADR-0005: Three-Way Reconciliation Engine with Exact and Fuzzy Fallback Matching

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
UPI payments span three independent systems (PSP app, payer bank CBS, central switch). Network timeouts, clock skew, and silent drops create breaks that simple two-way checks miss.

## Decision
Join `psp_ledger`, `payer_bank_ledger`, and `switch_ledger` primarily on `shared_ref`, falling back to fuzzy matching on `(payer_vpa_token, payee_vpa_token, amount_paise)` within a configurable time window (default 300s). Classify every discrepancy into 7 explicit break categories (`MISSING_IN_PSP`, `MISSING_IN_BANK`, `MISSING_IN_SWITCH`, `DUPLICATE`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `TIMING_BREAK`) and route breaks to an auditable `ExceptionQueue` (`OPEN -> INVESTIGATING -> RESOLVED`).

## Alternatives Considered
- Two-way PSP-to-Bank matching only (blind to central switch drops).

## Consequences
Every unique transaction reference is strictly conserved (`matched + broken == total_unique_refs`) and order-invariant.
