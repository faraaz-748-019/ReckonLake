-- ReconLake PostgreSQL Schema, Least-Privilege Roles, RLS & Tamper-Evident Audit Log

CREATE SCHEMA IF NOT EXISTS raw_gold;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS audit;

-- Base Gold tables loaded by Spark JDBC (etl_writer)
CREATE TABLE IF NOT EXISTS raw_gold.transactions (
    event_id TEXT PRIMARY KEY,
    shared_ref TEXT NOT NULL,
    txn_id TEXT NOT NULL,
    txn_type TEXT NOT NULL,
    state TEXT NOT NULL,
    amount_paise BIGINT NOT NULL,
    payer_vpa_token TEXT NOT NULL,
    payee_vpa_token TEXT NOT NULL,
    psp_app TEXT NOT NULL,
    payer_bank_id TEXT NOT NULL,
    failure_code TEXT,
    event_date DATE NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    tenant_region TEXT NOT NULL DEFAULT 'IN'
);

CREATE TABLE IF NOT EXISTS raw_gold.recon_summary (
    recon_date DATE NOT NULL,
    psp_app TEXT NOT NULL,
    payer_bank_id TEXT NOT NULL,
    total_transactions BIGINT NOT NULL,
    matched_count BIGINT NOT NULL,
    break_count BIGINT NOT NULL,
    quarantined_count BIGINT NOT NULL,
    PRIMARY KEY (recon_date, psp_app, payer_bank_id)
);

CREATE TABLE IF NOT EXISTS raw_gold.recon_breaks (
    break_id TEXT PRIMARY KEY,
    shared_ref TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    age_hours DOUBLE PRECISION NOT NULL,
    suggested_action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    recon_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_gold.dq_scores (
    batch_date DATE NOT NULL,
    source TEXT NOT NULL,
    completeness DOUBLE PRECISION NOT NULL,
    validity DOUBLE PRECISION NOT NULL,
    uniqueness DOUBLE PRECISION NOT NULL,
    timeliness DOUBLE PRECISION NOT NULL,
    consistency DOUBLE PRECISION NOT NULL,
    overall_score DOUBLE PRECISION NOT NULL,
    gate_passed BOOLEAN NOT NULL,
    PRIMARY KEY (batch_date, source)
);

-- Hash-chained immutable audit log
CREATE TABLE IF NOT EXISTS audit.audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    resource TEXT NOT NULL,
    details JSONB NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);

-- Revoke destructive operations on audit log from everyone except superuser
REVOKE ALL ON SCHEMA audit FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE ON audit.audit_log FROM PUBLIC;

-- Least-privilege grants
GRANT USAGE ON SCHEMA raw_gold TO etl_writer, dbt_runner;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA raw_gold TO etl_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA raw_gold TO dbt_runner;

GRANT USAGE, CREATE ON SCHEMA staging, gold TO dbt_runner;
GRANT USAGE ON SCHEMA gold TO analyst_masked, auditor_readonly;
GRANT USAGE ON SCHEMA audit TO auditor_readonly;
GRANT SELECT ON audit.audit_log TO auditor_readonly;
GRANT SELECT ON raw_gold.recon_breaks TO auditor_readonly;

-- Masked view: analyst_masked sees truncated/masked tokens only, never raw identifiers
CREATE OR REPLACE VIEW gold.vw_transactions_masked AS
SELECT
    event_id,
    shared_ref,
    txn_type,
    state,
    amount_paise,
    LEFT(payer_vpa_token, 12) || '...' AS payer_token_masked,
    LEFT(payee_vpa_token, 12) || '...' AS payee_token_masked,
    psp_app,
    payer_bank_id,
    event_date,
    tenant_region
FROM raw_gold.transactions;

GRANT SELECT ON gold.vw_transactions_masked TO analyst_masked;
REVOKE ALL ON raw_gold.transactions FROM analyst_masked;

-- Row-Level Security (RLS) on raw_gold.transactions
ALTER TABLE raw_gold.transactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_etl_writer_all ON raw_gold.transactions;
CREATE POLICY p_etl_writer_all ON raw_gold.transactions
    FOR ALL TO etl_writer USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS p_dbt_runner_read ON raw_gold.transactions;
CREATE POLICY p_dbt_runner_read ON raw_gold.transactions
    FOR SELECT TO dbt_runner USING (true);

DROP POLICY IF EXISTS p_analyst_region_only ON raw_gold.transactions;
CREATE POLICY p_analyst_region_only ON raw_gold.transactions
    FOR SELECT TO analyst_masked USING (tenant_region = current_setting('app.tenant_region', true));
