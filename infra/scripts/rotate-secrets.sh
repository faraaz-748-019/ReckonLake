#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SECRETS_DIR="${ROOT_DIR}/secrets"

mkdir -p "$SECRETS_DIR"
for secret_name in tokenizer_hmac_key envelope_kek postgres_etl_writer_password postgres_dbt_runner_password; do
  openssl rand -hex 32 > "${SECRETS_DIR}/${secret_name}"
  chmod 600 "${SECRETS_DIR}/${secret_name}"
  echo "Rotated: ${secret_name}"
done
echo "Rotation complete. Restart dependent services to pick up new Docker secrets."
