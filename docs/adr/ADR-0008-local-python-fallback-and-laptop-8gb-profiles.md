# ADR-0008: Docker Compose Resource Profiles and Local PyArrow Fallback Execution

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
Running Spark, Kafka, Airflow, Superset, Marquez, OpenBao, Prometheus, and Grafana simultaneously exceeds 8 GB RAM laptops, and developers on Windows may lack a local Hadoop `winutils.exe` binary.

## Decision
Organize `infra/docker-compose.yml` into Compose profiles (`core`, `streaming`, `governance`, `observability`, `stretch`) with explicit container memory limits so `core` fits inside 8 GB RAM, and provide a pure-Python/PyArrow Delta-compatible local execution path alongside PySpark jobs for rapid unit, property, chaos, and benchmark testing.

## Alternatives Considered
- Monolithic always-on Compose stack (OOMs on 8 GB laptops).

## Consequences
Full CI test suite, property tests, and demos execute deterministically in seconds locally while preserving full Spark/Docker parity.
