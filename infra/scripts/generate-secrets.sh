#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SECRETS_DIR="${ROOT_DIR}/secrets"
CERTS_DIR="${SECRETS_DIR}/certs"

mkdir -p "$SECRETS_DIR" "$CERTS_DIR"

generate_secret() {
  local name="$1"
  local target="${SECRETS_DIR}/${name}"
  if [[ ! -f "$target" ]]; then
    openssl rand -hex 32 > "$target"
    chmod 600 "$target"
    echo "Generated secret: $name"
  else
    echo "Secret already exists: $name"
  fi
}

generate_secret "postgres_admin_password"
generate_secret "postgres_etl_writer_password"
generate_secret "postgres_dbt_runner_password"
generate_secret "postgres_analyst_masked_password"
generate_secret "postgres_auditor_readonly_password"
generate_secret "openbao_root_token"
generate_secret "tokenizer_hmac_key"
generate_secret "envelope_kek"

if [[ ! -f "${CERTS_DIR}/local.crt" || ! -f "${CERTS_DIR}/local.key" ]]; then
  if command -v mkcert >/dev/null 2>&1; then
    mkcert -cert-file "${CERTS_DIR}/local.crt" -key-file "${CERTS_DIR}/local.key" localhost 127.0.0.1
  else
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout "${CERTS_DIR}/local.key" \
      -out "${CERTS_DIR}/local.crt" \
      -subj "/CN=reconlake.local"
  fi
  chmod 600 "${CERTS_DIR}/local.key"
  echo "Generated local TLS certificates in $CERTS_DIR"
fi

echo "All secrets and certs prepared in $SECRETS_DIR (never commit to Git)."
