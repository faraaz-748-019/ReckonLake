# Runbook: AuditChainVerificationFailure

- **Alert**: `AuditChainVerificationFailure` (`reconlake_audit_chain_valid == 0`)
- **Symptom**: `reconlake-verify-audit` detected a hash mismatch or broken `prev_hash` link in `audit.audit_log`.
- **Diagnosis**: Identify `first_tampered_index` from `reconlake-verify-audit` output and inspect PostgreSQL/host access logs.
- **Fix**: Treat as a **Critical Security Incident**. Preserve forensic snapshot, rotate all secrets (`make rotate-secrets`), restore verified chain from WORM backup.
- **Prevention**: Enforce `REVOKE UPDATE, DELETE, TRUNCATE` on `audit.audit_log` and periodic external hash anchoring.
