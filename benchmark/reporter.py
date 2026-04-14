"""Reporter: rich terminal table + JSON file output."""

from __future__ import annotations

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

    table.add_column("Tier (nodes)", justify="right", style="cyan", no_wrap=True)
    table.add_column("Batch Size", justify="right")
    table.add_column("Total Time", justify="right", style="green")
    table.add_column("Nodes/sec", justify="right", style="bold green")
    table.add_column("p50 (ms)", justify="right")
    table.add_column("p90 (ms)", justify="right")
    table.add_column("p95 (ms)", justify="right")
    table.add_column("p99 (ms)", justify="right", style="yellow")
    table.add_column("p99.9 (ms)", justify="right", style="red")
    table.add_column("Errors", justify="right", style="red")

    for tier in result.tiers:
        total_str = f"{tier.total_time_s:.2f}s"
        table.add_row(
            f"{tier.tier_nodes:,}",
            f"{tier.batch_size:,}",
            total_str,
            f"{tier.nodes_per_sec:,.0f}",
            f"{tier.p50_ms:.1f}",
            f"{tier.p90_ms:.1f}",
            f"{tier.p95_ms:.1f}",
            f"{tier.p99_ms:.1f}",
            f"{tier.p999_ms:.1f}",
            str(tier.error_count),
        )

    console.print()
    console.print(table)
    console.print()


def save_json(result: BenchmarkResult, directory: str = "results") -> str:
    """Save benchmark results to a timestamped JSON file. Returns the file path."""
    os.makedirs(directory, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(directory, f"benchmark_{ts}.json")
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    return path
