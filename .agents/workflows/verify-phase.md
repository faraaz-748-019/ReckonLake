# Verify Phase Workflow

> Trigger: `/verify-phase`

1. Run lint, type checks, unit and integration tests, and show the output.
2. Run the phase's acceptance checks and show evidence.
3. Run bandit, pip-audit, gitleaks and trivy on changed code.
4. Produce a Walkthrough artifact with results and any gaps. Do not hide failures.
