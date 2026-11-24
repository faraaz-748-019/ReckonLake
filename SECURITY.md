# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes     |

Only the latest release receives security fixes. Upgrade to the most recent version before filing a report.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report suspected security issues by emailing:

**security@example.com**

Include as much detail as possible:

| Field | Details |
|-------|---------|
| **Summary** | Brief one-line description |
| **Component** | Which module, service, or file is affected |
| **Impact** | What an attacker could achieve |
| **Steps to reproduce** | Minimal reproduction steps |
| **Suggested fix** | (optional) Your proposed remediation |

We will acknowledge receipt within **48 hours** and provide a status update within **7 days**.

---

## Disclosure Policy

We follow [Coordinated Vulnerability Disclosure (CVD)](https://vuls.cert.org/confluence/display/CVD/Executive+Summary):

1. Reporter contacts us privately.
2. We confirm and assess the issue.
3. We develop and test a fix.
4. We release the fix and credit the reporter (unless they prefer anonymity).
5. Public disclosure occurs **after** the fix is released — typically within 90 days of the initial report.

---

## Scope

### In-scope

- Authentication and authorisation bypass
- Injection vulnerabilities (SQL, command, JNDI, etc.)
- Secrets or credential leakage
- Insecure deserialization
- Broken access control in API endpoints
- Supply-chain attacks against pinned dependencies
- Docker image vulnerabilities affecting the runtime

### Out-of-scope

- Issues in third-party services this project merely integrates with
- Denial-of-service via resource exhaustion in a lab/demo environment
- Social engineering attacks
- Vulnerabilities requiring physical access to the host

---

## Security Design Principles

ReconLake follows a **defence-in-depth** approach:

- **No real credentials in source** — `.env`, `secrets/`, `*.key`, `*.pem` are gitignored and listed in `.antigravityignore`.
- **Secret management via OpenBao** — all runtime secrets are injected via the OpenBao agent sidecar; nothing is hard-coded.
- **Automated scanning** — `make security` runs Bandit (SAST), pip-audit (SCA), gitleaks (secrets), and Trivy (container CVE scan) on every CI run.
- **Pre-commit hooks** — gitleaks runs on every `git commit` to prevent accidental credential commits.
- **Least-privilege containers** — Docker services run as non-root users where possible.
- **Synthetic data only** — no real personal or financial data is ever used or stored; see `GEMINI.md`.

---

## Acknowledgements

We thank all security researchers who responsibly disclose vulnerabilities.
Your name (or handle) will be listed in `CHANGELOG.md` under the relevant release unless you request anonymity.
