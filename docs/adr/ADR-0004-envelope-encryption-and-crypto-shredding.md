# ADR-0004: Envelope Encryption and Crypto-Shredding for Immutable Lakehouse Erasure

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
Under India's DPDP Act and GDPR, customers have a right to erasure, yet Bronze Delta/Parquet files are append-only and immutable for auditability. Rewriting historical Parquet files for every deletion is brittle and expensive.

## Decision
Tokenize direct identifiers (VPA, phone, account) via deterministic HMAC-SHA256 at the Bronze boundary, and encrypt recoverable originals using per-token AES-256-GCM Data Encryption Keys (DEKs) wrapped by a Key-Encryption Key (KEK) from OpenBao Transit (or `LocalKeyService` fallback). Deleting a token's DEK (`reconlake-shred`) crypto-shreds the PII everywhere while analytical aggregates remain functional.

## Alternatives Considered
- In-place Parquet `DELETE` rewrites across Bronze/Silver/Gold (slow, breaks immutability).

## Consequences
Immutability and auditability are preserved alongside verifiable cryptographic erasure.
