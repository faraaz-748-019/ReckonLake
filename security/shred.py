"""
Crypto-shredding CLI & API for DPDP/GDPR right-to-erasure compliance.

Deletes a customer token's Data Encryption Key (DEK) from the key store and
records an immutable SHREDDING entry in the hash-chained audit log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from security.audit_chain import AuditChain
from security.envelope import EnvelopeEncryptor, FileKeyStore


def shred_token(
    token_id: str,
    keystore_path: Path,
    audit_path: Path,
    actor: str = "privacy-officer",
) -> dict[str, Any]:
    """Delete *token_id*'s DEK and append a SHREDDING event to the audit chain."""
    store = FileKeyStore(keystore_path)
    existed = store.has_key(token_id)
    enc = EnvelopeEncryptor(kek=b"\x01" * 32, dek_store=store)
    enc.shred(token_id)

    chain = AuditChain.load(audit_path) if audit_path.exists() else AuditChain()
    entry = chain.append(
        event_type="SHREDDING",
        actor=actor,
        resource=f"token:{token_id}",
        details={"key_existed": existed, "irreversible": True},
    )
    chain.save(audit_path)
    return {
        "token_id": token_id,
        "shredded": True,
        "key_existed": existed,
        "audit_entry_hash": entry.entry_hash,
    }


@click.command()
@click.option("--token-id", required=True, help="Token ID whose DEK should be crypto-shredded.")
@click.option("--keystore", default="data/keystore.json", show_default=True, help="Path to DEK keystore.")
@click.option("--audit-log", default="data/audit_chain.json", show_default=True, help="Path to audit chain file.")
@click.option("--actor", default="privacy-officer", show_default=True, help="Actor performing the erasure.")
def main(token_id: str, keystore: str, audit_log: str, actor: str) -> None:
    """Crypto-shred a customer token's data key so encrypted PII becomes permanently unreadable."""
    res = shred_token(token_id, Path(keystore), Path(audit_log), actor=actor)
    click.echo(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
