# ADR-0007: PostgreSQL Row-Level Security and Least-Privilege Service Roles

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
Serving analytical marts and audit tables in PostgreSQL requires strict separation between ETL writers, dbt transformers, masked analysts, and read-only auditors.

## Decision
Provision four least-privilege roles (`etl_writer`, `dbt_runner`, `analyst_masked`, `auditor_readonly`) in `infra/postgres/init.sql`, enforce Row-Level Security on `raw_gold.transactions`, expose only `gold.vw_transactions_masked` to `analyst_masked`, and revoke `UPDATE`/`DELETE`/`TRUNCATE` on `audit.audit_log`.

## Alternatives Considered
- Shared superuser credentials across Spark, Airflow, dbt, and Superset (unacceptable blast radius).

## Consequences
Over-privilege attempts are blocked at the database engine level and verified by `infra/postgres/rls_tests.sql`.
