# Data Engineering Rules (Always On)
- Every pipeline must be idempotent: re-running a batch produces the same result with no duplicates.
- Bronze is append-only and immutable. Silver deduplicates and enforces schema. Gold is business-ready.
- Every table has an owner, a data contract, a freshness SLA and documented columns.
- Failing records go to quarantine with a reason code. Never silently drop data.
- Use Delta MERGE for upserts, partition by event date, and record row counts at every layer.
- Emit OpenLineage events and Prometheus metrics from every job.
