"""
Consolidated security runner (`make security`).
Runs Bandit, pip-audit, and optional gitleaks/trivy checks, producing a single
JSON & Markdown report under docs/security/security-report.md.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_tool(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    return proc.returncode, proc.stdout, proc.stderr


def main() -> None:
    py = sys.executable
    findings: dict[str, Any] = {}
    failed = False

    # 1. Bandit SAST
    rc, out, err = _run_tool(
        [
            py,
            "-m",
            "bandit",
            "-r",
            "contracts",
            "generator",
            "pipelines",
            "security",
            "quality",
            "dags",
            "scripts",
            "-c",
            "pyproject.toml",
            "-ll",
            "-f",
            "json",
        ]
    )
    bandit_data = json.loads(out) if out.strip().startswith("{") else {"raw": out + err}
    high_bandit = [
        r for r in bandit_data.get("results", []) if r.get("issue_severity") in ("HIGH", "CRITICAL")
    ]
    findings["bandit"] = {
        "exit_code": rc,
        "total_issues": len(bandit_data.get("results", [])),
        "high_or_critical": len(high_bandit),
    }
    if high_bandit:
        failed = True

    # 2. pip-audit SCA
    rc_pa, out_pa, err_pa = _run_tool([py, "-m", "pip_audit", "--skip-editable", "--format", "json"])
    vulns: list[dict[str, Any]] = []
    if out_pa.strip().startswith("{"):
        pa_data = json.loads(out_pa)
        for dep in pa_data.get("dependencies", []):
            if dep.get("vulns"):
                vulns.append({"name": dep["name"], "version": dep["version"], "vulns": dep["vulns"]})
    findings["pip_audit"] = {
        "exit_code": rc_pa,
        "vulnerable_packages": len(vulns),
        "vulns": vulns,
        "error": err_pa.strip()[:300] if rc_pa != 0 and not vulns else "",
    }
    if rc_pa != 0:
        failed = True

    # 3. Optional binary scanners (gitleaks, trivy)
    for binary, args in [
        ("gitleaks", ["gitleaks", "detect", "--source", ".", "--no-banner"]),
        ("trivy", ["trivy", "fs", "--severity", "HIGH,CRITICAL", "--quiet", "."]),
    ]:
        if shutil.which(binary):
            rc_b, out_b, err_b = _run_tool(args)
            findings[binary] = {"installed": True, "exit_code": rc_b, "output": (out_b or err_b)[:500]}
            if rc_b != 0:
                failed = True
        else:
            findings[binary] = {"installed": False, "note": "Executed in GitHub Actions security.yml"}

    report_path = Path("docs/security/security-report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "# ReconLake Consolidated Security Scan Report\n\n```json\n"
        + json.dumps(findings, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(findings, indent=2))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
