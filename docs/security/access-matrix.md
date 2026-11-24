# RBAC Access Matrix

ReconLake enforces least-privilege access across every tier: SeaweedFS (S3), PostgreSQL, Airflow, Superset, and Python security policies.

## 1. PostgreSQL Roles (`infra/postgres/init.sql`)

| Role | `raw_gold.*` | `gold.vw_transactions_masked` | `staging.*` / `gold.*` marts | `audit.audit_log` |
|---|---|---|---|---|
| `etl_writer` | `SELECT, INSERT, UPDATE` | `NONE` | `NONE` | `NONE` (revoked) |
| `dbt_runner` | `SELECT` | `OWNER/CREATE` | `USAGE, CREATE` | `NONE` (revoked) |
| `analyst_masked` | **DENIED** (revoked + RLS) | `SELECT` (masked tokens, tenant RLS) | `SELECT` on Gold marts | `NONE` |
| `auditor_readonly` | `SELECT` on `recon_breaks` only | `NONE` | `USAGE` | `SELECT` only (`UPDATE/DELETE` revoked) |

## 2. SeaweedFS S3 Identities (`infra/seaweedfs/s3.json`)

| Identity | `bronze/*` | `silver/*` | `gold/*` | `quarantine/*` |
|---|---|---|---|---|
| `spark_bronze_writer` | Read, Write | None | None | Read, Write |
| `spark_silver_recon` | Read | Read, Write | Read, Write | Write |
| `auditor_readonly` | None | None | Read | Read |

## 3. Application / Python RBAC (`security/policies.py`)

| Role | Permitted Actions |
|---|---|
| `pipeline_writer` | `bronze:write`, `bronze:read`, `silver:write`, `silver:read`, `gold:write` |
| `analyst` | `gold:read`, `silver:read` |
| `reconciler` | `silver:read`, `gold:read`, `exception:read`, `exception:write` |
| `security_admin` | `keys:manage`, `keys:access`, `roles:assign`, `audit:read` |
| `auditor` | `audit:read` |
| `shredder` | `shred:execute` |

## 4. Superset & Airflow Roles
- **Superset**: `Gamma` read-only role bound to `analyst_masked` PostgreSQL credentials across all 4 provisioned dashboards.
- **Airflow**: `Admin` restricted to platform setup; `Op` for DAG triggers/backfills; `Viewer` for read-only inspection.
