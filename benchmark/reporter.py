"""Reporter: rich terminal table + JSON + CSV file output."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from benchmark.metrics import BenchmarkResult


def print_report(result: BenchmarkResult) -> None:
    """Print a rich table summarising the benchmark results."""
    console = Console()

    table = Table(
        title="FalkorDB Population Benchmark Results",
        show_lines=True,
    )

    table.add_column("Test Type", style="magenta", no_wrap=True)
    table.add_column("Tier (nodes)", justify="right", style="cyan", no_wrap=True)
    table.add_column("Batch Size", justify="right")
    table.add_column("Total Time", justify="right", style="green")
    table.add_column("Nodes/sec", justify="right", style="bold green")
    table.add_column("Avg Batch (ms)", justify="right")
    table.add_column("Batches", justify="right")
    table.add_column("Errors", justify="right", style="red")

    for tier in result.tiers:
        table.add_row(
            tier.test_type,
            f"{tier.tier_nodes:,}",
            f"{tier.batch_size:,}",
            f"{tier.total_time_s:.2f}s",
            f"{tier.nodes_per_sec:,.0f}",
            f"{tier.avg_batch_ms:.1f}",
            str(len(tier.batches)),
            str(tier.error_count),
        )

    console.print()
    console.print(table)
    console.print()


def _make_results_dir(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def save_json(result: BenchmarkResult, directory: str = "results") -> str:
    """Save benchmark results to a timestamped JSON file. Returns the file path."""
    ts = _make_results_dir(directory)
    path = os.path.join(directory, f"benchmark_{ts}.json")
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    return path


CSV_COLUMNS = [
    "test_type", "tier_nodes", "batch_size", "total_time_s", "nodes_per_sec",
    "avg_batch_ms", "success_batches", "error_batches", "total_batches",
]


def save_csv(result: BenchmarkResult, directory: str = "results") -> str:
    """Save benchmark results to a timestamped CSV file. Returns the file path."""
    ts = _make_results_dir(directory)
    path = os.path.join(directory, f"benchmark_{ts}.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for tier in result.tiers:
            writer.writerow(tier.to_dict())
    return path
