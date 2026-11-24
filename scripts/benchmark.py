"""
ReconLake Benchmark Runner.
Measures real generator + pipeline throughput, latency, and peak RSS memory,
and prints honest JSON results.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar

import click

from generator.producer import UPIGenerator
from pipelines.bronze.batch_ingest import run_batch_ingest
from pipelines.recon.recon_engine import evaluate_against_ground_truth, run_reconciliation_to_disk
from pipelines.silver.silver_pipeline import process_silver_records


def _peak_rss_mb() -> float:
    """Measure peak process resident set size (MB) with zero runtime overhead."""
    if platform.system() == "Windows":
        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_: ClassVar[list[tuple[str, Any]]] = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_bool
        handle = kernel32.GetCurrentProcess()
        psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return float(round(counters.PeakWorkingSetSize / (1024 * 1024), 2))
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)  # type: ignore[attr-defined]
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return float(round(usage.ru_maxrss / divisor, 2))


def benchmark_scale(count: int) -> dict[str, Any]:
    """Run generator + Bronze + Silver + Recon on *count* transactions and measure latency & RSS."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw_dir = root / "raw"
        bronze_dir = root / "bronze"
        silver_dir = root / "silver"
        q_dir = root / "quarantine"
        recon_dir = root / "recon"

        t0 = time.perf_counter()

        gen = UPIGenerator(seed=42, count=count, defect_profile="medium", fraud_profile="standard", batch_size=count)
        gen_stats = gen.write_files(raw_dir, file_format="jsonl")
        t_gen = time.perf_counter()

        for src in ("psp", "payer_bank", "switch"):
            run_batch_ingest(src, raw_dir, bronze_dir, q_dir)
        t_bronze = time.perf_counter()

        import pyarrow.parquet as pq

        for src in ("psp", "payer_bank", "switch"):
            rows = []
            sdir = bronze_dir / src
            if sdir.exists():
                for f in sorted(sdir.rglob("*.parquet")):
                    rows.extend(pq.ParquetFile(f).read().to_pylist())
            process_silver_records(
                records=rows,
                source=src,
                batch_date="2026-11-01",
                silver_dir=silver_dir,
                quarantine_dir=q_dir,
                enforce_circuit_breaker=False,
            )
        t_silver = time.perf_counter()

        recon_res = run_reconciliation_to_disk(silver_dir, recon_dir, "2026-11-01", quarantine_dir=q_dir)
        t_recon = time.perf_counter()

        defect_labels = [
            json.loads(line)
            for line in (raw_dir / "ground_truth" / "defect_labels.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        pr = evaluate_against_ground_truth(recon_res["breaks"], defect_labels)

        total_s = max(1e-6, t_recon - t0)
        return {
            "transactions": count,
            "ledger_events": gen_stats["total_ledger_events"],
            "gen_seconds": round(t_gen - t0, 3),
            "bronze_seconds": round(t_bronze - t_gen, 3),
            "silver_seconds": round(t_silver - t_bronze, 3),
            "recon_seconds": round(t_recon - t_silver, 3),
            "total_seconds": round(total_s, 3),
            "e2e_events_per_sec": round(gen_stats["total_ledger_events"] / total_s, 1),
            "peak_rss_mb": _peak_rss_mb(),
            "recon_precision_recall": pr,
        }


@click.command()
@click.option("--scales", default="10000,100000", show_default=True, help="Comma-separated transaction counts.")
def main(scales: str) -> None:
    """Run benchmarks and print JSON metrics."""
    results = [benchmark_scale(int(s.strip())) for s in scales.split(",") if s.strip()]
    payload = {
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "processor": platform.processor() or "unknown",
        },
        "results": results,
    }
    click.echo(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
