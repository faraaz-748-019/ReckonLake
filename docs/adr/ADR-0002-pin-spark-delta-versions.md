# ADR-0002: Pin Compatible Apache Spark and Delta Lake Versions

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
`pyspark` and `delta-spark` have strict binary/ABI compatibility requirements. Mismatched minor versions cause `NoSuchMethodError` or catalog extension failures at runtime.

## Decision
Pin `pyspark==3.5.3` with `delta-spark==3.2.0` in `pyproject.toml` and `infra/docker/spark/Dockerfile`, paired with OpenJDK 17 in the container image.

## Alternatives Considered
- Unpinned latest releases (risks silent breaking upgrades).
- Apache Iceberg (strong alternative, but Delta Lake was chosen for `MERGE` + time-travel simplicity in this design).

## Consequences
Reproducible Spark + Delta execution across CI, Docker containers, and local environments.
