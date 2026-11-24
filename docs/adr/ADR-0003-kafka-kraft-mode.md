# ADR-0003: Run Apache Kafka in KRaft Mode Without ZooKeeper

- **Status**: Accepted
- **Date**: 2026-11-24

## Context
Running ZooKeeper alongside Kafka consumes ~512 MB–1 GB of extra RAM and complicates healthchecks on an 8 GB laptop budget.

## Decision
Run `apache/kafka:3.8.1` in single-node KRaft mode (`broker,controller`), eliminating ZooKeeper completely.

## Alternatives Considered
- Kafka + ZooKeeper (deprecated upstream, higher memory footprint).

## Consequences
Faster startup, simpler Compose topology, and ~500 MB RAM saved in the `core` profile.
