#!/usr/bin/env bash
set -euo pipefail

ETL_PW=$(cat /run/secrets/postgres_etl_writer_password)
DBT_PW=$(cat /run/secrets/postgres_dbt_runner_password)
ANALYST_PW=$(cat /run/secrets/postgres_analyst_masked_password)
AUDITOR_PW=$(cat /run/secrets/postgres_auditor_readonly_password)

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_writer') THEN
      CREATE ROLE etl_writer NOINHERIT LOGIN PASSWORD '${ETL_PW}';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dbt_runner') THEN
      CREATE ROLE dbt_runner NOINHERIT LOGIN PASSWORD '${DBT_PW}';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analyst_masked') THEN
      CREATE ROLE analyst_masked NOINHERIT LOGIN PASSWORD '${ANALYST_PW}';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auditor_readonly') THEN
      CREATE ROLE auditor_readonly NOINHERIT LOGIN PASSWORD '${AUDITOR_PW}';
    END IF;
  END
  \$\$;
EOSQL
