# ADR-0006: Versioned YAML Data Contracts, Quarantine, and DQ Circuit Breaker

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
Schema drift and null keys in upstream payment feeds must never crash streaming ingestion or silently corrupt Gold settlement reports.

## Decision
Define versioned YAML contracts (`contracts/*.yaml`) enforced at Bronze and Silver via Pydantic + JSONSchema (`contracts/validator.py`), check backward compatibility in CI (`contracts/compat.py`), route invalid records to quarantine tables with reason codes and payload SHA-256 hashes, and gate Gold promotion behind a 5-dimension Data Quality Score circuit breaker (`quality/dq_score.py`).

## Alternatives Considered
- Schema-on-read with silent row filtering (violates zero-silent-drop rule).

## Consequences
Zero silent data loss; breaking contract edits fail CI unless accompanied by a major version bump and ADR.
