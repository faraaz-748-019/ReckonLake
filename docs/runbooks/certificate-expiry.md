# Runbook: CertificateExpirySoon

- **Alert**: `CertificateExpirySoon` (`reconlake_tls_cert_expiry_days < 14`)
- **Symptom**: Local Traefik TLS certificate in `secrets/certs/local.crt` expires within 14 days.
- **Diagnosis**: Run `openssl x509 -enddate -noout -in secrets/certs/local.crt`.
- **Fix**: Remove old cert and run `make generate-secrets`, then reload Traefik (`make up PROFILE=core`).
- **Prevention**: Schedule quarterly local cert rotation.
