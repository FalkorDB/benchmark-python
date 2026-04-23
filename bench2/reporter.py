"""CSV (rolling, append-only) + per-run markdown summary."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from bench2.runner import RunResult


CSV_FIELDS = [
    "run_id", "timestamp", "benchmark", "indexed",
    "ops", "batch_size", "total_s", "ops_per_sec",
    "per_op_avg_ms", "per_op_p50_ms", "per_op_p95_ms", "per_op_p99_ms",
]


def _row(run_id: str, ts: str, r: RunResult) -> dict:
    return {
        "run_id": run_id,
        "timestamp": ts,
        "benchmark": r.benchmark,
        "indexed": str(r.indexed).lower(),
        "ops": r.ops,
        "batch_size": r.batch_size,
        "total_s": r.total_s,
        "ops_per_sec": r.ops_per_sec,
        "per_op_avg_ms": r.per_op_avg_ms,
        "per_op_p50_ms": r.per_op_p50_ms,
        "per_op_p95_ms": r.per_op_p95_ms,
        "per_op_p99_ms": r.per_op_p99_ms,
    }


def append_csv(csv_path: Path, run_id: str, results: list[RunResult]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not csv_path.exists()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with csv_path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()
        for r in results:
            w.writerow(_row(run_id, ts, r))


def _delta_pct(b1: float, b2: float) -> str:
    if b1 == 0:
        return "—"
    pct = (b2 - b1) / b1 * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def write_markdown_summary(md_path: Path, run_id: str, results: list[RunResult]) -> None:
    """Side-by-side comparison table across all benchmarks in this run."""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not results:
        return

    metrics = [
        ("ops/sec",            "ops_per_sec",   ",.1f"),
        ("per-op avg (ms)",    "per_op_avg_ms", ".4f"),
        ("per-op p50 (ms)",    "per_op_p50_ms", ".4f"),
        ("per-op p95 (ms)",    "per_op_p95_ms", ".4f"),
        ("per-op p99 (ms)",    "per_op_p99_ms", ".4f"),
        ("per-op min (ms)",    "per_op_min_ms", ".4f"),
        ("per-op max (ms)",    "per_op_max_ms", ".4f"),
        ("total_s (measured)", "total_s",       ".3f"),
        ("success batches",    "success_batches", "d"),
        ("error batches",      "error_batches",   "d"),
    ]

    def fmt(value, spec: str) -> str:
        if spec == "d":
            return str(int(value))
        return format(value, spec)

    header = "| Metric | " + " | ".join(f"{r.benchmark}" for r in results) + " |"
    sep    = "|--------|" + "|".join(["---:"] * len(results)) + "|"

    lines = [
        f"# bench2 — run {run_id}",
        "",
        f"- **Run timestamp (UTC):** {ts}",
        f"- **Workloads run:** {', '.join(r.benchmark for r in results)}",
        f"- **Ops per benchmark (measured):** {results[0].ops:,}  "
        f"(first {results[0].warmup_batches} batches × {results[0].batch_size} discarded as warm-up)",
        f"- **Batch size:** {results[0].batch_size} ops",
        "",
        "## Side-by-side",
        "",
        header,
        sep,
    ]
    for label, attr, spec in metrics:
        row = f"| {label} | " + " | ".join(fmt(getattr(r, attr), spec) for r in results) + " |"
        lines.append(row)

    # Honest note if B3 is in the mix — it does different work per op.
    if any(r.benchmark.startswith("merge_upsert") for r in results):
        lines.append("")
        lines.append("> **Note on direct comparison:** `merge_pair_*` ops touch 2 nodes + 1 edge per op; "
                     "`merge_upsert_label_swap` touches 1 node + adds/removes labels per op. "
                     "ops/sec is therefore not directly comparable between pair and upsert workloads. "
                     "Use per-op latency for like-for-like reasoning, and treat the upsert numbers as a "
                     "reproduction of the customer (W7) pattern on the same indexed graph.")

    lines.append("")
    md_path.write_text("\n".join(lines))
