"""CLI entry point for the FalkorDB CRM-aligned population benchmark."""

from __future__ import annotations

import sys
import time
import click
from rich.console import Console

from benchmark.data_gen import (
    PopulationPlan, TestType, ENTITY_LABEL,
    generate_batch, generate_edges_for_batch,
)
from benchmark.falkor_client import BenchmarkClient
from benchmark.metrics import MetricsCollector, BenchmarkResult
from benchmark.reporter import print_report, save_json, save_csv
from benchmark.init import ensure_init, graph_name_for
from benchmark.runner import run_workload
from benchmark.workloads import Workload, WorkloadSpec

DEFAULT_TIERS = [500_000, 750_000]
DEFAULT_SUITE_TIERS = [100_000, 250_000, 500_000, 750_000]
DEFAULT_NOINDEX_TIERS = [100_000, 250_000]  # unindexed only viable at small tiers
ALL_TEST_TYPES = list(TestType)
ALL_WORKLOADS = list(Workload)

console = Console(force_terminal=False, force_interactive=False)


def _log(msg: str) -> None:
    console.print(msg)
    sys.stdout.flush()


def _run_tier(
    client: BenchmarkClient,
    tier_nodes: int,
    batch_size: int,
    test_type: TestType,
):
    plan = PopulationPlan(
        tier_nodes=tier_nodes,
        batch_size=batch_size,
        test_type=test_type,
    )
    collector = MetricsCollector(
        label=test_type.value,
        total_units=tier_nodes,
        batch_size=batch_size,
    )

    client.delete_graph()
    if plan.needs_uuid_index:
        client.create_uuid_pair_index(ENTITY_LABEL)

    collector.start()
    log_every = max(1, plan.num_batches // 20)  # ~5% increments
    expected_edges = 0

    # Single combined query per batch: nodes + edges in one round-trip.
    for i in range(plan.num_batches):
        start_id = i * batch_size
        actual = min(batch_size, tier_nodes - start_id)
        nodes = generate_batch(start_id, actual)
        edges = generate_edges_for_batch(nodes)
        expected_edges += len(edges)

        result = client.execute_query(
            plan.combined_query,
            params={"nodes": nodes, "edges": edges},
        )
        collector.record_batch(
            batch_index=i,
            batch_size=actual,
            duration_ms=result.duration_ms,
            success=result.success,
            error=result.error,
            merge_ms=result.duration_ms,
            promote_ms=0.0,
            edge_ms=0.0,
        )
        del nodes, edges

        if (i + 1) % log_every == 0 or i + 1 == plan.num_batches:
            done = min((i + 1) * batch_size, tier_nodes)
            _log(f"    {done:,}/{tier_nodes:,} nodes  ({time.perf_counter() - collector._start:.1f}s)")

    from benchmark.metrics import TierResult as _TR
    tier_result = _TR(
        tier_nodes=tier_nodes,
        batch_size=batch_size,
        test_type=test_type.value,
        total_time_s=collector.total_time_s(),
        batches=collector.batches,
    )
    tier_result.compute()

    actual_nodes, actual_edges = client.graph_size()
    if actual_nodes != tier_nodes:
        _log(f"    [yellow]⚠ Expected {tier_nodes:,} nodes, found {actual_nodes:,}[/yellow]")
    if actual_edges != expected_edges:
        _log(f"    [yellow]⚠ Expected {expected_edges:,} edges, found {actual_edges:,}[/yellow]")

    return tier_result


@click.group()
def main():
    """FalkorDB CRM Population Benchmark Tool."""


@main.command()
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--graph", default="benchmark", show_default=True)
@click.option("--tiers", multiple=True, type=int,
              help="Node counts per tier (repeatable). Defaults: 500K 750K 1M 1.5M.")
@click.option("--batch-size", default=1000, show_default=True)
@click.option("--tests", multiple=True,
              type=click.Choice([t.value for t in TestType], case_sensitive=False))
@click.option("--save/--no-save", default=True, show_default=True)
@click.option("--csv/--no-csv", "save_csv_flag", default=True, show_default=True)
def populate(host, port, username, password, graph, tiers, batch_size, tests, save, save_csv_flag):
    """Run the CRM-aligned population benchmark across growth tiers.

    Every batch creates its 1000 nodes AND their edges (10 edges per group of 5 nodes)
    in a single Cypher round-trip. All variants use :entity + :account labels and a
    numeric UUID stored as (uuid_hi, uuid_lo) int64 pair.

    \b
    Variants:
      merge_baseline  — MERGE :entity:account + edges, NO uuid index
      merge_indexed   — MERGE :entity:account + edges, range index on (uuid_hi, uuid_lo)
      inactive_flow   — two-phase MERGE (:inactive -> :account) + edges, indexed
    """
    tier_list = list(tiers) if tiers else DEFAULT_TIERS
    test_types = [TestType(t) for t in tests] if tests else ALL_TEST_TYPES

    _log("\n[bold]FalkorDB CRM Population Benchmark[/bold]")
    _log(f"  Host: {host}:{port}  Graph: {graph}  User: {username or '(none)'}")
    _log(f"  Tiers: {', '.join(f'{t:,}' for t in tier_list)} nodes")
    _log(f"  Tests: {', '.join(t.value for t in test_types)}")
    _log(f"  Batch size: {batch_size:,}  |  Total runs: {len(tier_list)*len(test_types)}")
    _log("  Each batch: nodes + edges in one Cypher round-trip\n")

    client = BenchmarkClient(
        host=host, port=port, graph_name=graph,
        username=username, password=password,
    )
    benchmark_result = BenchmarkResult()

    for tier_nodes in tier_list:
        for test_type in test_types:
            _log(f"[bold cyan]▶ {test_type.value} @ {tier_nodes:,}[/bold cyan]")
            tier_result = _run_tier(client, tier_nodes, batch_size, test_type)
            benchmark_result.tiers.append(tier_result)
            _log(
                f"  [green]✓[/green] {test_type.value} @ {tier_nodes:,}: "
                f"{tier_result.total_time_s:.1f}s, "
                f"{tier_result.nodes_per_sec:,.0f} nodes/s "
                f"(avg batch {tier_result.avg_batch_ms:.1f}ms, "
                f"{tier_result.success_count}/{len(tier_result.batches)} batches OK)\n"
            )
            if save:
                save_json(benchmark_result)
            if save_csv_flag:
                save_csv(benchmark_result)

    print_report(benchmark_result)
    if save:
        path = save_json(benchmark_result)
        _log(f"[dim]Results saved to {path}[/dim]")
    if save_csv_flag:
        csv_path = save_csv(benchmark_result)
        _log(f"[dim]CSV saved to {csv_path}[/dim]")

    client.delete_graph()


# -----------------------------------------------------------------------------
# Phase 1: init
# -----------------------------------------------------------------------------

@main.command("init")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--tier", required=True, type=int, help="Target node count for the init graph.")
@click.option("--no-index", "no_index", is_flag=True, default=False,
              help="Skip the uuid composite index (unindexed init graph).")
@click.option("--batch-size", default=1000, show_default=True)
@click.option("--force", is_flag=True, default=False,
              help="Rebuild even if a graph of this size already exists.")
@click.option("--accept-pain", is_flag=True, default=False,
              help="Required to run --no-index at tiers > 500K (slow/quadratic).")
@click.option("--throttle-ms", default=0.0, type=float, show_default=True,
              help="Sleep N ms between batches to lower server load.")
def init_cmd(host, port, username, password, tier, no_index, batch_size, force, accept_pain,
             throttle_ms):
    """Phase 1: load a baseline CRM graph at the requested tier size.

    Creates a graph named `crm_init_<tier>` (or `crm_init_<tier>_noindex` when
    --no-index is passed), populated with `:entity:account` nodes and
    `:CONNECTED_TO` edges. This graph is the starting point for `benchmark run`
    and `benchmark suite`.
    """
    indexed = not no_index
    if not indexed and tier > 500_000 and not accept_pain:
        raise click.ClickException(
            f"--no-index at tier {tier:,} is quadratic and will likely never finish. "
            f"Pass --accept-pain to force it, or use smaller tiers."
        )

    _log(f"\n[bold]FalkorDB init[/bold]  tier={tier:,}  indexed={indexed}  batch={batch_size:,}  throttle={throttle_ms}ms")
    ensure_init(
        host=host, port=port,
        size=tier, indexed=indexed, batch_size=batch_size, force=force,
        username=username, password=password,
        log=_log, throttle_ms=throttle_ms,
    )


# -----------------------------------------------------------------------------
# Phase 2: run (single workload)
# -----------------------------------------------------------------------------

@main.command("run")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--tier", required=True, type=int, help="Init graph tier to measure against.")
@click.option("--no-index", is_flag=True, default=False,
              help="Use the unindexed init graph (must already exist).")
@click.option("--workload", "workloads_opt", multiple=True,
              type=click.Choice([w.value for w in Workload]),
              help="One or more workloads (repeatable). Default: all.")
@click.option("--ops", default=100_000, show_default=True, type=int,
              help="Operations per workload run.")
@click.option("--batch-size", default=1000, show_default=True)
@click.option("--save/--no-save", default=True, show_default=True)
@click.option("--csv/--no-csv", "save_csv_flag", default=True, show_default=True)
@click.option("--throttle-ms", default=0.0, type=float, show_default=True,
              help="Sleep N ms between batches to lower server load.")
def run_cmd(host, port, username, password, tier, no_index,
            workloads_opt, ops, batch_size, save, save_csv_flag, throttle_ms):
    """Phase 2: run one or more workloads against an existing init graph."""
    indexed = not no_index
    graph = graph_name_for(tier, indexed)

    selected = [Workload(w) for w in workloads_opt] if workloads_opt else ALL_WORKLOADS

    _log(f"\n[bold]CRM Workload Run[/bold]")
    _log(f"  Graph: {graph}  (tier={tier:,}, indexed={indexed})")
    _log(f"  Workloads: {', '.join(w.value for w in selected)}")
    _log(f"  Ops: {ops:,}  Batch: {batch_size:,}\n")

    client = BenchmarkClient(
        host=host, port=port, graph_name=graph,
        username=username, password=password,
    )

    pre_n, _ = client.graph_size()
    if pre_n < tier:
        raise click.ClickException(
            f"Init graph '{graph}' not ready ({pre_n:,} nodes; expected {tier:,}). "
            f"Run `benchmark init --tier {tier}{' --no-index' if no_index else ''}` first."
        )

    result = BenchmarkResult()
    for idx, w in enumerate(selected):
        _log(f"[bold cyan]▶ {w.value} @ tier={tier:,}  idx={indexed}[/bold cyan]")
        spec = WorkloadSpec(workload=w, init_size=tier, ops_count=ops,
                            batch_size=batch_size, id_offset=idx * 2 * ops)
        wr = run_workload(client, spec, indexed=indexed, log=_log, throttle_ms=throttle_ms)
        result.workloads.append(wr)
        _log(f"  [green]✓[/green] {w.value}: {wr.total_time_s:.2f}s  "
             f"{wr.ops_per_sec:,.0f} ops/s  avg={wr.avg_batch_ms:.2f}ms  "
             f"p95={wr.p95_batch_ms:.2f}ms  errors={wr.error_count}\n")
        if save:
            save_json(result)
        if save_csv_flag:
            save_csv(result)

    print_report(result)
    if save:
        _log(f"[dim]JSON: {save_json(result)}[/dim]")
    if save_csv_flag:
        _log(f"[dim]CSV:  {save_csv(result)}[/dim]")


# -----------------------------------------------------------------------------
# Phase 2: suite (matrix of tiers × index × workloads)
# -----------------------------------------------------------------------------

@main.command("suite")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=6379, show_default=True)
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--tiers", multiple=True, type=int,
              help="Tiers (repeatable). Default: 100K 250K 500K 750K 1M 1.5M.")
@click.option("--no-index-tiers", multiple=True, type=int,
              help="Which tiers also run unindexed (default: 100K 250K).")
@click.option("--workload", "workloads_opt", multiple=True,
              type=click.Choice([w.value for w in Workload]),
              help="Restrict workloads (repeatable). Default: all 8.")
@click.option("--ops", default=100_000, show_default=True, type=int)
@click.option("--batch-size", default=1000, show_default=True)
@click.option("--skip-init", is_flag=True, default=False,
              help="Assume all init graphs already exist; fail if any are missing.")
@click.option("--save/--no-save", default=True, show_default=True)
@click.option("--csv/--no-csv", "save_csv_flag", default=True, show_default=True)
@click.option("--throttle-ms", default=0.0, type=float, show_default=True,
              help="Sleep N ms between batches (applied to both init and workloads).")
def suite_cmd(host, port, username, password, tiers, no_index_tiers,
              workloads_opt, ops, batch_size, skip_init, save, save_csv_flag, throttle_ms):
    """Phase 2 matrix: all workloads × tiers × (indexed, unindexed-for-small-tiers)."""
    tier_list = list(tiers) if tiers else DEFAULT_SUITE_TIERS
    nox_tiers = list(no_index_tiers) if no_index_tiers else DEFAULT_NOINDEX_TIERS
    nox_tiers = [t for t in nox_tiers if t in tier_list]
    selected = [Workload(w) for w in workloads_opt] if workloads_opt else ALL_WORKLOADS

    runs = [(t, True) for t in tier_list] + [(t, False) for t in nox_tiers]
    total_runs = len(runs) * len(selected)

    _log("\n[bold]CRM Workload Suite[/bold]")
    _log(f"  Tiers: {', '.join(f'{t:,}' for t in tier_list)}")
    _log(f"  Unindexed tiers: {', '.join(f'{t:,}' for t in nox_tiers) or '(none)'}")
    _log(f"  Workloads: {', '.join(w.value for w in selected)}")
    _log(f"  Ops/workload: {ops:,}  Batch: {batch_size:,}  Total runs: {total_runs}\n")

    result = BenchmarkResult()

    for tier_size, indexed in runs:
        graph = graph_name_for(tier_size, indexed)
        _log(f"[bold]━━━ tier={tier_size:,}  indexed={indexed}  graph={graph} ━━━[/bold]")

        if skip_init:
            client = BenchmarkClient(
                host=host, port=port, graph_name=graph,
                username=username, password=password,
            )
            pre_n, _ = client.graph_size()
            if pre_n < tier_size:
                raise click.ClickException(
                    f"--skip-init set but '{graph}' has {pre_n:,} < {tier_size:,} nodes."
                )
        else:
            client = ensure_init(
                host=host, port=port,
                size=tier_size, indexed=indexed,
                batch_size=batch_size, force=False,
                username=username, password=password,
                log=_log, throttle_ms=throttle_ms,
            )

        for idx, w in enumerate(selected):
            _log(f"[bold cyan]▶ {w.value}[/bold cyan]")
            spec = WorkloadSpec(
                workload=w, init_size=tier_size, ops_count=ops,
                batch_size=batch_size, id_offset=idx * 2 * ops,
            )
            wr = run_workload(client, spec, indexed=indexed, log=_log, throttle_ms=throttle_ms)
            result.workloads.append(wr)
            _log(f"  [green]✓[/green] {wr.total_time_s:.2f}s  "
                 f"{wr.ops_per_sec:,.0f} ops/s  avg={wr.avg_batch_ms:.2f}ms  "
                 f"p95={wr.p95_batch_ms:.2f}ms  errors={wr.error_count}\n")
            if save:
                save_json(result)
            if save_csv_flag:
                save_csv(result)

    print_report(result)
    if save:
        _log(f"[dim]JSON: {save_json(result)}[/dim]")
    if save_csv_flag:
        _log(f"[dim]CSV:  {save_csv(result)}[/dim]")


if __name__ == "__main__":
    main()
