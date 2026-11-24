"""
CLI command `verify-audit` to verify integrity of the hash-chained audit log.
Exits non-zero if tampering is detected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from security.audit_chain import AuditChain


@click.command()
@click.option("--audit-log", default="data/audit_chain.json", show_default=True, help="Path to audit chain JSON.")
def main(audit_log: str) -> None:
    """Verify hash-chain integrity of the ReconLake audit log."""
    path = Path(audit_log)
    if not path.exists():
        click.echo(json.dumps({"valid": False, "error": f"Audit log not found: {path}"}))
        sys.exit(1)

    chain = AuditChain.load(path)
    valid, bad_idx = chain.verify()
    result = {
        "valid": valid,
        "entries_checked": len(chain),
        "first_tampered_index": bad_idx,
        "head_hash": chain.head_hash(),
    }
    click.echo(json.dumps(result, indent=2))
    if not valid:
        sys.exit(1)


if __name__ == "__main__":
    main()
