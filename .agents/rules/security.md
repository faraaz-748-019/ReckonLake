# Security Rules (Always On)
- Never commit secrets, keys, tokens or .env files. Use Docker secrets and SOPS.
- Never log raw identifiers. Log only tokens.
- Every container: non-root user, read_only root filesystem where possible, cap_drop ALL, no-new-privileges.
- Validate and parameterise all inputs. No string-built SQL.
- Use well-known crypto libraries only. Never invent crypto. AES-256-GCM with unique nonces.
- Pin dependency versions. Run pip-audit, bandit, gitleaks and trivy before declaring done.
- Principle of least privilege for every service account.
