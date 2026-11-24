"""File-drop batch Bronze ingestion CLI & helper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from pipelines.bronze.streaming_ingest import ingest_records_to_bronze

LEDGER_FILES = {
    "psp": "psp_ledger.jsonl",
    "payer_bank": "payer_bank_ledger.jsonl",
    "switch": "switch_ledger.jsonl",
}


def run_batch_ingest(
    source: str,
    raw_dir: Path,
    bronze_dir: Path,
    quarantine_dir: Path,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    """Ingest a JSONL file drop for *source* into Bronze + Quarantine."""
    file_path = raw_dir / LEDGER_FILES[source]
    if not file_path.exists():
        raise FileNotFoundError(f"Raw ledger file not found: {file_path}")

    records: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    ckpt = (checkpoint_dir / f"{source}.ckpt.json") if checkpoint_dir else None
    return ingest_records_to_bronze(
        records=records,
        source=source,
        bronze_dir=bronze_dir,
        quarantine_dir=quarantine_dir,
        checkpoint_path=ckpt,
    )


@click.command()
@click.option("--source", required=True, type=click.Choice(["psp", "payer_bank", "switch"]))
@click.option("--raw-dir", default="data/raw", show_default=True)
@click.option("--bronze-dir", default="data/bronze", show_default=True)
@click.option("--quarantine-dir", default="data/quarantine", show_default=True)
def main(source: str, raw_dir: str, bronze_dir: str, quarantine_dir: str) -> None:
    """Run batch Bronze ingestion for a single ledger source."""
    res = run_batch_ingest(
        source=source,
        raw_dir=Path(raw_dir),
        bronze_dir=Path(bronze_dir),
        quarantine_dir=Path(quarantine_dir),
        checkpoint_dir=Path(bronze_dir) / "_checkpoints",
    )
    click.echo(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
