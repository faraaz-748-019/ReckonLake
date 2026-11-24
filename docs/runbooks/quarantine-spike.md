# Runbook: QuarantineSpike

- **Alert**: `QuarantineSpike` (`rate(reconlake_rows_quarantined_total[5m]) > 50`)
- **Symptom**: Sudden surge in rejected records at Bronze or Silver boundary.
- **Diagnosis**: Group `data/quarantine/` records by `reason_code` to distinguish `SCHEMA_DRIFT` vs `PII_EXPOSURE` vs `NULL_KEY`.
- **Fix**: Coordinate producer rollback or contract update; replay quarantined payloads once corrected.
- **Prevention**: Pre-release contract tests with upstream producers.
