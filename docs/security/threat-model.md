# ReconLake STRIDE Threat Model

This document maps threats across all **STRIDE** categories to implemented controls and automated verification tests.

## Data Classification
- **Restricted**: Direct identifiers (VPA, phone, account number) — tokenized at Bronze boundary; encrypted via AES-256-GCM envelope keys.
- **Confidential**: Transaction amounts, timestamps, failure codes, break records.
- **Internal**: Aggregated Gold KPIs, DQ scores, anonymous metrics.

## Threat-to-Control-to-Test Matrix

| ID | STRIDE Category | Threat Scenario | Control Implemented | Verification Test |
|---|---|---|---|---|
| **T1** | **Spoofing** | Rogue service or caller impersonates an internal writer or analyst | Segmented Docker networks (`ingest_net`, `data_net`, `serving_net`); distinct PostgreSQL roles (`etl_writer`, `dbt_runner`, `analyst_masked`, `auditor_readonly`); distinct SeaweedFS S3 identities (`infra/seaweedfs/s3.json`) | `infra/postgres/rls_tests.sql`, `tests/unit/test_security.py::test_rbac_least_privilege` |
| **T2** | **Tampering** | Attacker or insider alters historical audit log entries or Bronze events | Hash-chained `AuditChain` (`security/audit_chain.py`), `REVOKE UPDATE, DELETE, TRUNCATE` on `audit.audit_log`, `reconlake-verify-audit` CLI, append-only Bronze with `raw_payload_sha256` | `tests/unit/test_security.py::test_audit_chain_detects_tampering`, `tests/integration/test_bronze_silver_gold_e2e.py::test_abuse_audit_tampering_caught_after_save` |
| **T3** | **Repudiation** | Operator denies shredding a key or modifying exception queue state | Mandatory `AuditChain` append on `SHREDDING`, `KEY_ACCESS`, `ROLE_CHANGE`, `EXCEPTION_QUEUE_CHANGE`; immutable `exception_history` | `tests/unit/test_recon.py::test_exception_queue_workflow_and_audit` |
| **T4** | **Information Disclosure (Logs & Storage)** | Raw VPAs, phone numbers, or account numbers leak into logs, Bronze Parquet, or analyst views | Bronze `enforce_tokenization_boundary()` (`pipelines/bronze/streaming_ingest.py`); HMAC-SHA256 tokens (`security/tokenizer.py`); PostgreSQL masked view `gold.vw_transactions_masked` + RLS; Traefik TLS termination | `tests/integration/test_bronze_silver_gold_e2e.py::test_abuse_no_raw_pii_in_logs_or_bronze` |
| **T5** | **Information Disclosure (Right to Erasure)** | Deleted customer's encrypted PII remains recoverable from immutable Bronze backups | Per-token AES-256-GCM DEK envelope encryption + crypto-shredding (`security/envelope.py`, `security/shred.py`) | `tests/unit/test_security.py::test_envelope_encrypt_decrypt_and_crypto_shred` |
| **T6** | **Information Disclosure (SQLi & Secrets)** | SQL injection on query endpoints or secrets leaked in Git history | Parameterised SQL queries (`?` / `$1`); Docker secrets (`infra/scripts/generate-secrets.sh`); `.gitignore` & `.antigravityignore`; gitleaks + Bandit + Semgrep in CI | `tests/integration/test_bronze_silver_gold_e2e.py::test_abuse_sql_injection_blocked_by_parameterised_queries`, `.github/workflows/security.yml` |
| **T7** | **Denial of Service** | Poisoned / schema-drifted / null-key event stream crashes Spark or corrupts Gold | Strict YAML data contracts (`contracts/*.yaml`), quarantine routing with reason codes, DQ circuit breaker (`quality/dq_score.py`), container memory limits in `infra/docker-compose.yml` | `tests/unit/test_contracts.py`, `tests/unit/test_silver.py::test_silver_circuit_breaker_halts_gold` |
| **T8** | **Elevation of Privilege** | Container escape or `analyst_masked` gaining write/raw access | `cap_drop: [ALL]`, `no-new-privileges: true`, non-root users, `read_only: true` root filesystems, RBAC `is_allowed()` matrix, PostgreSQL `REVOKE ALL ON raw_gold.transactions FROM analyst_masked` | `tests/unit/test_security.py::test_rbac_least_privilege`, `infra/postgres/rls_tests.sql` |
