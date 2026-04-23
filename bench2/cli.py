"""bench2 CLI — `bench2 init`, `bench2 run`, `bench2 full`."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import click

from benchmark.falkor_client import BenchmarkClient
from bench2.init import init_graph
from bench2.runner import run_benchmark
from bench2.reporter import append_csv, write_markdown_summary


@click.group()
def main() -> None:
    """bench2 — index-impact micro-benchmark."""


def _client(host: str, port: int, graph: str, username: str | None, password: str | None) -> BenchmarkClient:
    return BenchmarkClient(host=host, port=port, graph_name=graph, username=username, password=password)


@main.command("init")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True, type=int)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--graph", required=True, help="Target graph name (will be DROPPED).")
@click.option("--indexed/--no-index", default=True, show_default=True,
              help="Create composite uuid index BEFORE loading.")
@click.option("--nodes", default=100_000, show_default=True, type=int)
@click.option("--batch-size", default=100, show_default=True, type=int)
@click.option("--extra-contacts", default=0, show_default=True, type=int,
              help="Also load N :entity:contact nodes (sharing the composite index) "
                   "to test noisy-neighbor effects on the indexed account-MERGE.")
def init_cmd(host, port, username, password, graph, indexed, nodes, batch_size, extra_contacts) -> None:
    """Drop the graph and load the baseline."""
    client = _client(host, port, graph, username, password)
    n, e = init_graph(client, num_nodes=nodes, indexed=indexed, batch_size=batch_size,
                      extra_contacts=extra_contacts)
    click.echo(f"OK — {n:,} nodes / {e:,} edges (indexed={indexed}, extra_contacts={extra_contacts:,})")


@main.command("run")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True, type=int)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--graph", required=True)
@click.option("--name", required=True, help="Label for this run (e.g. merge_pair_indexed).")
@click.option("--indexed/--no-index", default=True, show_default=True,
              help="Just metadata for the result row; does not change the graph.")
@click.option("--start-id", default=200_000, show_default=True, type=int,
              help="First sequential id used by the benchmark (must be past init range).")
@click.option("--ops", default=25_000, show_default=True, type=int,
              help="Number of pairs (each pair = 2 nodes + 1 edge).")
@click.option("--batch-size", default=100, show_default=True, type=int)
@click.option("--warmup-batches", default=10, show_default=True, type=int)
@click.option("--workload", type=click.Choice(["pair", "upsert"]), default="pair",
              show_default=True,
              help="pair = B1/B2 MERGE-pair query; upsert = B3 customer W7 single-MERGE+SET=+label-swap")
def run_cmd(host, port, username, password, graph, name, indexed, start_id, ops, batch_size, warmup_batches, workload) -> None:
    """Run the measured benchmark against an existing init graph."""
    client = _client(host, port, graph, username, password)
    pre_n, pre_e = client.graph_size()
    click.echo(f"[run] pre: {pre_n:,} nodes / {pre_e:,} edges  (graph={graph}, workload={workload})")
    extra = {}
    if workload == "upsert":
        from bench2.workload import UPSERT_LABEL_SWAP_QUERY, iter_single_batches
        extra = {"query": UPSERT_LABEL_SWAP_QUERY, "iter_fn": iter_single_batches}
    r = run_benchmark(
        client, name=name, indexed=indexed, start_id=start_id,
        num_pairs=ops, batch_size=batch_size, warmup_batches=warmup_batches,
        **extra,
    )
    click.echo(f"[run] {r.benchmark}: {r.ops_per_sec:,.0f} ops/s  "
               f"avg={r.per_op_avg_ms:.4f} ms/op  p95={r.per_op_p95_ms:.4f}  p99={r.per_op_p99_ms:.4f}")


@main.command("full")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True, type=int)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--graph-prefix", default="bench2", show_default=True,
              help="Graph names will be <prefix>_no_index, <prefix>_indexed, <prefix>_upsert.")
@click.option("--nodes", default=50_000, show_default=True, type=int)
@click.option("--ops", default=25_000, show_default=True, type=int)
@click.option("--batch-size", default=100, show_default=True, type=int)
@click.option("--warmup-batches", default=10, show_default=True, type=int)
@click.option("--results-dir", default="results-b2", show_default=True)
@click.option("--include-b3/--no-b3", default=True, show_default=True,
              help="Also run B3 (customer upsert_label_swap pattern on indexed graph).")
def full_cmd(host, port, username, password, graph_prefix, nodes, ops, batch_size, warmup_batches, results_dir, include_b3) -> None:
    """Run all benchmarks (B1, B2, optionally B3), append CSV, write markdown summary."""
    from bench2.workload import UPSERT_LABEL_SWAP_QUERY, iter_single_batches

    run_id = uuid.uuid4().hex[:8]
    click.echo(f"=== bench2 full run {run_id} ===")

    legs = [
        ("merge_pair_no_index",     False, "no_index", None,                      None),
        ("merge_pair_indexed",      True,  "indexed",  None,                      None),
    ]
    if include_b3:
        legs.append(
            ("merge_upsert_label_swap", True,  "upsert",   UPSERT_LABEL_SWAP_QUERY, iter_single_batches),
        )

    results = []
    for name, indexed, suffix, query, iter_fn in legs:
        graph_name = f"{graph_prefix}_{suffix}"
        click.echo(f"\n--- {name} (graph={graph_name}, indexed={indexed}) ---")
        client = _client(host, port, graph_name, username, password)
        init_graph(client, num_nodes=nodes, indexed=indexed, batch_size=batch_size)
        r = run_benchmark(
            client, name=name, indexed=indexed,
            start_id=2 * nodes,
            num_pairs=ops, batch_size=batch_size, warmup_batches=warmup_batches,
            query=query, iter_fn=iter_fn,
        )
        click.echo(f"=> {r.ops_per_sec:,.0f} ops/s  avg={r.per_op_avg_ms:.4f} ms/op  "
                   f"p50={r.per_op_p50_ms:.4f}  p95={r.per_op_p95_ms:.4f}  p99={r.per_op_p99_ms:.4f}")
        results.append(r)

    out_dir = Path(results_dir)
    csv_path = out_dir / "results_b2.csv"
    md_path = out_dir / f"summary_{run_id}.md"
    append_csv(csv_path, run_id, results)
    write_markdown_summary(md_path, run_id, results)

    click.echo(f"\nCSV appended: {csv_path}")
    click.echo(f"Summary:      {md_path}")


if __name__ == "__main__":
    main()
