# ADR-0001: Use Free Open-Source Stack; Reject MinIO and Proprietary Tools

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
ReconLake must run 100% locally on an 8 GB RAM laptop with zero cloud accounts, zero paid licences, and zero proprietary vendor lock-in.

## Decision
Use exclusively free, permissive/OSI open-source tools:
- **Object Storage**: SeaweedFS (Apache 2.0) with its S3 API (`bronze`, `silver`, `gold`, `quarantine` buckets).
- **Streaming**: Apache Kafka in KRaft mode (Apache 2.0).
- **Compute & Lakehouse**: Apache Spark + Delta Lake (Apache 2.0).
- **Orchestration & Transformation**: Apache Airflow + dbt Core (dbt-postgres).
- **Serving & BI**: PostgreSQL 16 + Apache Superset.
- **Lineage & Observability**: OpenLineage / Marquez + Prometheus / Grafana / Alertmanager.
- **Secrets & Transit**: OpenBao (MPL-2.0 fork of Vault) with a local Python AES-256-GCM fallback key service.

## Alternatives Considered
- **MinIO**: Rejected. MinIO community edition stopped shipping container images in October 2025 and its repository was archived in April 2026; SeaweedFS provides an actively maintained Apache 2.0 S3-compatible store.
- **Managed Cloud / Databricks**: Rejected due to cost, cloud account requirement, and lack of local offline reproducibility.

## Consequences
All core components are self-contained in Docker Compose profiles and reproducible offline.
