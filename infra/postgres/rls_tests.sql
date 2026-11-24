-- SQL verification tests for PostgreSQL least-privilege roles & RLS
-- Execute against PostgreSQL after running infra/postgres/init.sql

-- 1. Verify analyst_masked CANNOT read raw_gold.transactions directly
SET ROLE analyst_masked;
-- Expected: permission denied for table transactions
SELECT COUNT(*) FROM raw_gold.transactions;
RESET ROLE;

-- 2. Verify analyst_masked CAN read masked view when tenant_region matches RLS
SET ROLE analyst_masked;
SET app.tenant_region = 'IN';
SELECT event_id, payer_token_masked, amount_paise FROM gold.vw_transactions_masked LIMIT 5;
RESET ROLE;

-- 3. Verify auditor_readonly CAN read audit_log and recon_breaks, CANNOT DELETE audit_log
SET ROLE auditor_readonly;
SELECT COUNT(*) FROM audit.audit_log;
SELECT COUNT(*) FROM raw_gold.recon_breaks;
-- Expected: permission denied for table audit_log
DELETE FROM audit.audit_log;
RESET ROLE;

-- 4. Verify etl_writer CANNOT UPDATE or DELETE audit.audit_log
SET ROLE etl_writer;
-- Expected: permission denied for schema audit
UPDATE audit.audit_log SET actor = 'tamper';
RESET ROLE;
