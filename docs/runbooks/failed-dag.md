# Runbook: FailedAirflowDAG

- **Alert**: `FailedAirflowDAG` (`reconlake_dag_failures_total > 0`)
- **Symptom**: One or more tasks in `ingest_batch`, `silver_pipeline`, `recon_daily`, or `gold_load_and_dbt` failed.
- **Diagnosis**: Inspect Airflow task logs and Marquez run failure status.
- **Fix**: Clear the failed task in Airflow UI; tasks are idempotent so retry produces zero duplicates.
- **Prevention**: Maintain unit + chaos tests in CI (`tests/chaos/test_chaos_recovery.py`).
