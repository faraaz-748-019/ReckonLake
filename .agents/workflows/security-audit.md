# Security Audit Workflow

> Trigger: `/security-audit`

1. Review the repo against the STRIDE threat model in docs/security/threat-model.md.
2. Check every control in section 5 of the project brief: present, tested, documented.
3. Attempt abuse cases: SQL injection, secret leakage in logs, overly broad roles, tampered audit log.
4. Report findings ranked by severity and fix the High ones.
