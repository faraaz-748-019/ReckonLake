# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-25

### Added
- **Phase 0**: Repository skeleton, `pyproject.toml`, `Makefile`, `.pre-commit-config.yaml`, GitHub Actions (`ci.yml`, `security.yml`), MkDocs Material site, 8 ADRs (`ADR-0001`–`ADR-0008`).
- **Phase 1**: Seeded reproducible synthetic UPI lifecycle generator (`generator/`) with 3 ledgers, 5 fraud typologies, 8 defect injectors, Kafka + JSONL/Parquet outputs, and ground-truth labels.
- **Phase 2**: Hardened Docker Compose stack (`infra/docker-compose.yml`) with `core`, `streaming`, `governance`, `observability`, `stretch` profiles, SeaweedFS (S3), Kafka KRaft, PostgreSQL least-privilege roles, OpenBao, and Traefik TLS.
- **Phase 3**: Versioned YAML data contracts (`contracts/*.yaml`), Pydantic+JSONSchema validator, CI breaking-change detector (`contracts/compat.py`), Bronze ingestion with tokenization boundary and quarantine.
- **Phase 4**: Idempotent Silver layer (`pipelines/silver/`), Great Expectations checks, 5-dimension Data Quality Score, and DQ circuit breaker.
- **Phase 5**: O(N) three-way reconciliation engine (`pipelines/recon/`) with 7 break categories, fuzzy fallback matching, `ExceptionQueue` workflow, and ground-truth precision/recall reporting.
- **Phase 6**: Gold marts (`pipelines/gold/`, `dbt/`), PostgreSQL Row-Level Security + masked views, and 4 Superset dashboards-as-code.
- **Phase 7**: Six data-aware Airflow DAGs (`dags/`) with Alertmanager failure callbacks and OpenLineage dataset + column-level lineage emission.
- **Phase 8**: AES-256-GCM envelope encryption, `reconlake-shred` crypto-shredding CLI, `AuditChain` + `reconlake-verify-audit` CLI, STRIDE threat model, RBAC access matrix, and security abuse tests.
- **Phase 9**: Prometheus alerts, 4 Grafana dashboards, 6 operational runbooks, SLOs, mid-run crash/recovery chaos tests, and 10k/100k benchmarks (`docs/benchmarks.md`).
- **Phase 10**: End-to-end `scripts/demo.py`, `docs/traceability.md`, `docs/demo.md`, `docs/learning/phase-0-to-10.md`, and `v1.0.0` release preparation.
