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
    """Print rich tables summarising the benchmark results."""
    console = Console()

    if result.tiers:
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

    if result.workloads:
        print_workload_report(result, console=console)
        print_delta_tables(result, console=console)

    console.print()


def print_workload_report(result: BenchmarkResult, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(
        title="CRM Workload Benchmark (headline metrics)",
        show_lines=True,
    )
    table.add_column("Workload", style="magenta", no_wrap=True)
    table.add_column("Tier", justify="right", style="cyan")
    table.add_column("Idx", justify="center")
    table.add_column("Ops/sec", justify="right", style="bold green")
    table.add_column("Avg (ms)", justify="right")
    table.add_column("p95 (ms)", justify="right")
    table.add_column("Total (s)", justify="right", style="green")
    table.add_column("Err", justify="right", style="red")

    for w in result.workloads:
        table.add_row(
            w.workload,
            f"{w.tier_nodes:,}",
            "✓" if w.indexed else "—",
            f"{w.ops_per_sec:,.0f}",
            f"{w.avg_batch_ms:.2f}",
            f"{w.p95_batch_ms:.2f}",
            f"{w.total_time_s:.2f}",
            str(w.error_count),
        )
    console.print()
    console.print(table)


def print_delta_tables(result: BenchmarkResult, console: Console | None = None) -> None:
    """Print indexed-vs-unindexed and MERGE-vs-CREATE delta tables."""
    console = console or Console()

    # Group results: key by (workload, tier_nodes) -> {True: wr, False: wr}
    by_key: dict[tuple[str, int], dict[bool, object]] = {}
    for w in result.workloads:
        by_key.setdefault((w.workload, w.tier_nodes), {})[w.indexed] = w

    # Index-delta table: for (workload, tier) where both indexed+unindexed exist.
    pairs = [(k, v) for k, v in by_key.items() if True in v and False in v]
    if pairs:
        t = Table(title="Indexed vs Unindexed: ops/sec speedup (indexed / unindexed)",
                  show_lines=True)
        t.add_column("Workload", style="magenta")
        t.add_column("Tier", justify="right", style="cyan")
        t.add_column("Indexed ops/s", justify="right", style="green")
        t.add_column("Unindexed ops/s", justify="right")
        t.add_column("Speedup (×)", justify="right", style="bold yellow")
        for (wl, tier), variants in sorted(pairs):
            idx = variants[True]
            nox = variants[False]
            if nox.ops_per_sec <= 0:
                speed = "∞"
            else:
                speed = f"{idx.ops_per_sec / nox.ops_per_sec:.2f}×"
            t.add_row(wl, f"{tier:,}", f"{idx.ops_per_sec:,.0f}",
                      f"{nox.ops_per_sec:,.0f}", speed)
        console.print()
        console.print(t)

    # MERGE-vs-CREATE delta for W1 and W2.
    merge_create_pairs = [
        ("insert_attach_merge", "insert_attach_create"),
        ("insert_pair_merge", "insert_pair_create"),
    ]
    by_wl_tier_idx: dict = {}
    for w in result.workloads:
        by_wl_tier_idx[(w.workload, w.tier_nodes, w.indexed)] = w

    rows = []
    for m_name, c_name in merge_create_pairs:
        for (wl, tier, idx), _ in list(by_wl_tier_idx.items()):
            if wl != m_name:
                continue
            m = by_wl_tier_idx.get((m_name, tier, idx))
            c = by_wl_tier_idx.get((c_name, tier, idx))
            if m and c:
                rows.append((m_name.replace("_merge", ""), tier, idx, m, c))
    if rows:
        t = Table(title="MERGE vs CREATE: ops/sec ratio (create / merge)", show_lines=True)
        t.add_column("Workload", style="magenta")
        t.add_column("Tier", justify="right", style="cyan")
        t.add_column("Idx", justify="center")
        t.add_column("MERGE ops/s", justify="right")
        t.add_column("CREATE ops/s", justify="right", style="green")
        t.add_column("Ratio (×)", justify="right", style="bold yellow")
        seen = set()
        for key, tier, idx, m, c in sorted(rows):
            if (key, tier, idx) in seen:
                continue
            seen.add((key, tier, idx))
            ratio = (c.ops_per_sec / m.ops_per_sec) if m.ops_per_sec > 0 else float("inf")
            t.add_row(key, f"{tier:,}", "✓" if idx else "—",
                      f"{m.ops_per_sec:,.0f}", f"{c.ops_per_sec:,.0f}", f"{ratio:.2f}×")
        console.print()
        console.print(t)


def _make_results_dir(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def save_json(result: BenchmarkResult, directory: str = "results") -> str:
    ts = _make_results_dir(directory)
    path = os.path.join(directory, f"benchmark_{ts}.json")
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    return path


CSV_COLUMNS = [
    "test_type", "tier_nodes", "batch_size", "total_time_s", "nodes_per_sec",
    "avg_batch_ms", "success_batches", "error_batches", "total_batches",
]

WORKLOAD_CSV_COLUMNS = [
    "workload", "tier_nodes", "indexed", "ops_count", "batch_size",
    "total_time_s", "ops_per_sec",
    "avg_batch_ms", "p50_batch_ms", "p95_batch_ms", "p99_batch_ms",
    "min_batch_ms", "max_batch_ms",
    "success_batches", "error_batches", "total_batches",
    "pre_nodes", "post_nodes", "pre_edges", "post_edges",
    "delta_nodes", "delta_edges",
]


def save_csv(result: BenchmarkResult, directory: str = "results") -> str:
    ts = _make_results_dir(directory)
    # Tier CSV (populate command back-compat)
    if result.tiers:
        path = os.path.join(directory, f"benchmark_{ts}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for tier in result.tiers:
                writer.writerow(tier.to_dict())
    else:
        path = None

    # Workload CSV
    if result.workloads:
        wpath = os.path.join(directory, f"workloads_{ts}.csv")
        with open(wpath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=WORKLOAD_CSV_COLUMNS)
            writer.writeheader()
            for wr in result.workloads:
                writer.writerow(wr.to_dict())
        path = path or wpath

    return path or ""

