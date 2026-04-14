"""CLI entry point for the FalkorDB population benchmark."""

from __future__ import annotations

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from benchmark.data_gen import PopulationPlan, TestType
from benchmark.falkor_client import BenchmarkClient
from benchmark.metrics import MetricsCollector, BenchmarkResult
from benchmark.reporter import print_report, save_json, save_csv

DEFAULT_TIERS = [10_000, 50_000, 100_000, 500_000, 1_000_000]

ALL_TEST_TYPES = [TestType.BASELINE, TestType.UUID, TestType.UUID_INDEXED]

console = Console()


def _run_tier(
    client: BenchmarkClient,
    tier_nodes: int,
    batch_size: int,
    test_type: TestType,
    label: str,
    progress: Progress,
) -> "benchmark.metrics.TierResult":
    """Populate one tier with a specific test type and collect metrics."""

    plan = PopulationPlan(
        tier_nodes=tier_nodes,
        batch_size=batch_size,
        test_type=test_type,
        label=label,
    )
    collector = MetricsCollector(
        tier_nodes=tier_nodes,
        batch_size=batch_size,
        test_type=test_type.value,
    )

    task = progress.add_task(
        f"[cyan]{test_type.value:<12} {tier_nodes:>9,} nodes",
        total=plan.num_batches,
    )

    # Fresh graph for each run
    client.delete_graph()
    client.create_index(label)
    if test_type == TestType.UUID_INDEXED:
        client.create_uuid_index(label)

    collector.start()
    for batch_idx, batch_data in plan.iter_batches():
        result = client.execute_query(plan.query, params={"nodes": batch_data})
        collector.record_batch(
            batch_index=batch_idx,
            batch_size=len(batch_data),
            duration_ms=result.duration_ms,
            success=result.success,
            error=result.error,
        )
        progress.update(task, advance=1)

    tier_result = collector.finish()

    # Verify node count
    actual_nodes, _ = client.graph_size()
    if actual_nodes != tier_nodes:
        console.print(
            f"  [yellow]⚠ Expected {tier_nodes:,} nodes but found {actual_nodes:,}[/yellow]"
        )

    return tier_result


@click.group()
def main():
    """FalkorDB Population Benchmark Tool."""
    pass


@main.command()
@click.option("--host", default="localhost", show_default=True, help="FalkorDB host")
@click.option("--port", default=6379, show_default=True, help="FalkorDB port")
@click.option("--graph", default="benchmark", show_default=True, help="Graph name")
@click.option(
    "--tiers",
    multiple=True,
    type=int,
    help="Node counts per tier (repeatable). Defaults to 10K 50K 100K 500K 1M.",
)
@click.option("--batch-size", default=500, show_default=True, help="Nodes per UNWIND batch")
@click.option("--label", default="Entity", show_default=True, help="Node label")
@click.option(
    "--tests",
    multiple=True,
    type=click.Choice(["baseline", "uuid", "uuid_indexed"], case_sensitive=False),
    help="Test types to run (repeatable). Defaults to all three.",
)
@click.option("--save/--no-save", default=True, show_default=True, help="Save JSON results")
@click.option("--csv/--no-csv", "save_csv_flag", default=True, show_default=True, help="Save CSV results")
def populate(host: str, port: int, graph: str, tiers: tuple[int, ...], batch_size: int, label: str, tests: tuple[str, ...], save: bool, save_csv_flag: bool):
    """Run the population benchmark across growth tiers.

    Runs three test types per tier by default:
      baseline     — 100 properties, no UUID
      uuid         — 100 properties + UUID property
      uuid_indexed — 100 properties + UUID property + index on UUID
    """
    tier_list = list(tiers) if tiers else DEFAULT_TIERS
    test_types = [TestType(t) for t in tests] if tests else ALL_TEST_TYPES
    total_runs = len(tier_list) * len(test_types)

    console.print(f"\n[bold]FalkorDB Population Benchmark[/bold]")
    console.print(f"  Host: {host}:{port}  Graph: {graph}")
    console.print(f"  Tiers: {', '.join(f'{t:,}' for t in tier_list)} nodes")
    console.print(f"  Tests: {', '.join(t.value for t in test_types)}")
    console.print(f"  Batch size: {batch_size:,}  Label: {label}")
    console.print(f"  Properties per node: 100  |  Total runs: {total_runs}\n")

    client = BenchmarkClient(host=host, port=port, graph_name=graph)
    benchmark_result = BenchmarkResult()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        for tier_nodes in tier_list:
            for test_type in test_types:
                tier_result = _run_tier(
                    client, tier_nodes, batch_size, test_type, label, progress
                )
                benchmark_result.tiers.append(tier_result)

    print_report(benchmark_result)

    if save:
        path = save_json(benchmark_result)
        console.print(f"[dim]Results saved to {path}[/dim]")

    if save_csv_flag:
        csv_path = save_csv(benchmark_result)
        console.print(f"[dim]CSV saved to {csv_path}[/dim]")

    console.print()

    # Cleanup
    client.delete_graph()


if __name__ == "__main__":
    main()
