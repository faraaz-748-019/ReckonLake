"""CLI entrypoint for the ReconLake synthetic UPI generator."""

from __future__ import annotations

import json

import click

from generator.producer import DEFECT_PROFILES, FRAUD_PROFILES, UPIGenerator


@click.command()
@click.option("--seed", default=42, show_default=True, type=int, help="PRNG seed for reproducibility.")
@click.option("--count", default=100_000, show_default=True, type=int, help="Number of canonical transactions.")
@click.option("--rate", default=1000, show_default=True, type=int, help="Target event rate (events/sec).")
@click.option(
    "--defect-profile",
    default="medium",
    show_default=True,
    type=click.Choice(list(DEFECT_PROFILES)),
    help="Data-quality defect injection profile.",
)
@click.option(
    "--fraud-profile",
    default="standard",
    show_default=True,
    type=click.Choice(list(FRAUD_PROFILES)),
    help="Fraud typology injection profile.",
)
@click.option(
    "--mode",
    default="file",
    show_default=True,
    type=click.Choice(["file", "kafka"]),
    help="Output mode: file drop or Kafka topics.",
)
@click.option(
    "--format",
    "file_format",
    default="jsonl",
    show_default=True,
    type=click.Choice(["jsonl", "parquet", "both"]),
    help="File output format when --mode=file.",
)
@click.option("--output-dir", default="./data/raw", show_default=True, help="Directory for file-drop output.")
@click.option("--kafka-bootstrap", default=None, help="Kafka bootstrap servers when --mode=kafka.")
def main(
    seed: int,
    count: int,
    rate: int,
    defect_profile: str,
    fraud_profile: str,
    mode: str,
    file_format: str,
    output_dir: str,
    kafka_bootstrap: str | None,
) -> None:
    """Generate seeded synthetic UPI multi-ledger payment events."""
    gen = UPIGenerator(
        seed=seed,
        count=count,
        rate=rate,
        defect_profile=defect_profile,
        fraud_profile=fraud_profile,
    )
    if mode == "kafka":
        stats = gen.produce_kafka(bootstrap_servers=kafka_bootstrap)
    else:
        stats = gen.write_files(output_dir=output_dir, file_format=file_format)
    click.echo(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
