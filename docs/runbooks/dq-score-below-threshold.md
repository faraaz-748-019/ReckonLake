# Runbook: DQScoreBelowThreshold

- **Alert**: `DQScoreBelowThreshold` (`reconlake_dq_score < 0.90` for 5m)
- **Symptom**: Gold promotion halted by `DQCircuitBreaker`; batch remains in `silver_pending/`.
- **Diagnosis**:
  1. Inspect latest DQ score JSON in `data/silver/_dq_scores/`.
  2. Query quarantine Parquet files under `data/quarantine/` grouped by `reason_code`.
- **Fix**:
  1. Contact upstream source owner if `NULL_KEY` or `SCHEMA_DRIFT` spiked.
  2. Fix upstream feed or update contract + ADR, then replay batch via Airflow `backfill` DAG.
- **Prevention**: Enforce backward-compatible contract checks (`contracts/compat.py`) on every PR.
