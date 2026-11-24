# Runbook: StreamLagHigh

- **Alert**: `StreamLagHigh` (`reconlake_stream_lag_seconds > 120` for 5m)
- **Symptom**: Bronze Kafka consumer falling behind producer offsets.
- **Diagnosis**:
  1. Check Spark container CPU/RAM (`docker stats`) and Kafka consumer lag.
- **Fix**:
  1. Increase Spark executor parallelism or batch trigger interval; verify SeaweedFS health (`/cluster/status`).
- **Prevention**: Keep `core` Compose resource limits tuned and monitor Kafka partition count.
