"""
Contract backward-compatibility checker for CI.

Compares a new YAML contract against a previous version and fails on breaking
changes (removed field, type change, tightened nullability, narrowed enum)
unless a major version bump AND an ADR in docs/adr/ are present.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
import yaml


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = [int(p) for p in version.strip().split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def check_breaking_change(old_contract: dict[str, Any], new_contract: dict[str, Any]) -> list[str]:
    """Return a list of breaking-change descriptions between *old_contract* and *new_contract*."""
    breaking: list[str] = []
    old_fields = {f["name"]: f for f in old_contract.get("schema", [])}
    new_fields = {f["name"]: f for f in new_contract.get("schema", [])}

    for name, old_f in old_fields.items():
        if name not in new_fields:
            breaking.append(f"Removed field '{name}'")
            continue
        new_f = new_fields[name]
        if old_f.get("type") != new_f.get("type"):
            breaking.append(f"Type changed on '{name}': {old_f.get('type')} -> {new_f.get('type')}")
        if old_f.get("nullable", False) and not new_f.get("nullable", False):
            breaking.append(f"Tightened nullability on '{name}': nullable true -> false")
        old_enum = set(old_f.get("enum") or [])
        new_enum = set(new_f.get("enum") or [])
        if old_enum and new_enum and not old_enum.issubset(new_enum):
            removed_vals = sorted(old_enum - new_enum)
            breaking.append(f"Removed enum values on '{name}': {removed_vals}")

    # Adding a new non-nullable field is also breaking for backward compatibility
    for name, new_f in new_fields.items():
        if name not in old_fields and not new_f.get("nullable", False):
            breaking.append(f"Added required (non-nullable) field '{name}'")

    return breaking


def is_breaking_allowed(
    old_contract: dict[str, Any],
    new_contract: dict[str, Any],
    adr_dir: Path,
) -> tuple[bool, list[str]]:
    """
    Validate contract evolution.
    Breaking changes are allowed ONLY if major version bumped AND an ADR exists.
    """
    breaks = check_breaking_change(old_contract, new_contract)
    if not breaks:
        return True, []

    old_maj, _, _ = _parse_semver(str(old_contract["version"]))
    new_maj, _, _ = _parse_semver(str(new_contract["version"]))
    has_major_bump = new_maj > old_maj
    has_adr = any(adr_dir.glob("ADR-*.md")) if adr_dir.exists() else False

    if has_major_bump and has_adr:
        return True, breaks
    return False, breaks


@click.command()
@click.option("--base-ref", default="HEAD~1", help="Git ref to compare contracts against.")
@click.option("--contracts-dir", default="contracts", help="Directory containing YAML contracts.")
@click.option("--adr-dir", default="docs/adr", help="Directory containing ADRs.")
def main(base_ref: str, contracts_dir: str, adr_dir: str) -> None:
    """Verify backward compatibility of modified contracts against *base_ref*."""
    cdir = Path(contracts_dir)
    adir = Path(adr_dir)
    failed = False

    for yaml_path in sorted(cdir.glob("*.yaml")):
        rel = yaml_path.as_posix()
        git_bin = shutil.which("git") or "git"
        proc = subprocess.run(  # noqa: S603
            [git_bin, "show", f"{base_ref}:{rel}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            click.echo(f"[NEW] {rel} (no prior version at {base_ref})")
            continue
        old_c = yaml.safe_load(proc.stdout)
        new_c = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        allowed, breaks = is_breaking_allowed(old_c, new_c, adir)
        if not allowed:
            click.echo(f"[FAIL] Breaking changes in {rel} without major bump + ADR: {breaks}", err=True)
            failed = True
        elif breaks:
            click.echo(f"[WARN] Breaking changes in {rel} permitted by major version bump + ADR: {breaks}")
        else:
            click.echo(f"[OK] {rel} is backward compatible.")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
