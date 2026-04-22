"""Phase 2: per-workload runner."""

from __future__ import annotations

import sys
import time

from benchmark.falkor_client import BenchmarkClient
from benchmark.metrics import MetricsCollector, WorkloadResult
from benchmark.workloads import Workload, WorkloadSpec


def _sample_inactive_uuids(client: BenchmarkClient, limit: int) -> list[tuple[int, int]]:
    """Grab up to `limit` uuid pairs of :inactive nodes from the graph."""
    q = f"MATCH (n:inactive) RETURN n.uuid_hi, n.uuid_lo LIMIT {int(limit)}"
    try:
        rs = client.graph.query(q).result_set
    except Exception:
        return []
    return [(row[0], row[1]) for row in rs if row[0] is not None and row[1] is not None]


def run_workload(
    client: BenchmarkClient,
    spec: WorkloadSpec,
    indexed: bool,
    log=print,
    throttle_ms: float = 0.0,
) -> WorkloadResult:
    """Execute one workload against `client`'s current graph. Return aggregated result."""
    pre_nodes, pre_edges = client.graph_size()

    inactive_pool: list[tuple[int, int]] | None = None
    if spec.workload == Workload.W6_PROMOTE:
        inactive_pool = _sample_inactive_uuids(client, spec.ops_count)
        if not inactive_pool:
            log(f"    [yellow]⚠ W6: no :inactive nodes present; skipping[/yellow]")
            return WorkloadResult(
                workload=spec.workload.value,
                tier_nodes=spec.init_size,
                indexed=indexed,
                ops_count=0,
                batch_size=spec.batch_size,
                total_time_s=0.0,
                pre_nodes=pre_nodes, post_nodes=pre_nodes,
                pre_edges=pre_edges, post_edges=pre_edges,
            )
        if len(inactive_pool) < spec.ops_count:
            log(f"    [yellow]⚠ W6: only {len(inactive_pool):,} :inactive nodes "
                f"available (< {spec.ops_count:,} requested); cycling[/yellow]")

    collector = MetricsCollector(
        label=spec.workload.value,
        total_units=spec.ops_count,
        batch_size=spec.batch_size,
    )
    collector.start()
    query = spec.query
    log_every = max(1, int(spec.num_batches * 0.10))

    for batch_idx, ops in spec.iter_batches(existing_inactive_uuids=inactive_pool):
        result = client.execute_query(query, params={"ops": ops})
        collector.record_batch(
            batch_index=batch_idx,
            batch_size=len(ops),
            duration_ms=result.duration_ms,
            success=result.success,
            error=result.error,
        )
        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)
        if (batch_idx + 1) % log_every == 0 or batch_idx + 1 == spec.num_batches:
            done = min((batch_idx + 1) * spec.batch_size, spec.ops_count)
            log(f"    {done:,}/{spec.ops_count:,} ops  "
                f"({time.perf_counter() - collector._start:.1f}s)")
            sys.stdout.flush()

    total = collector.total_time_s()
    post_nodes, post_edges = client.graph_size()

    wr = WorkloadResult(
        workload=spec.workload.value,
        tier_nodes=spec.init_size,
        indexed=indexed,
        ops_count=spec.ops_count,
        batch_size=spec.batch_size,
        total_time_s=total,
        batches=collector.batches,
        pre_nodes=pre_nodes, post_nodes=post_nodes,
        pre_edges=pre_edges, post_edges=post_edges,
    )
    wr.compute()

    # sanity check
    exp_nodes = spec.expected_node_delta
    exp_edges = spec.expected_edge_delta
    actual_dn = post_nodes - pre_nodes
    actual_de = post_edges - pre_edges
    if exp_nodes is not None and actual_dn != exp_nodes:
        log(f"    [yellow]⚠ node delta: expected {exp_nodes:+,}, got {actual_dn:+,}[/yellow]")
    if exp_edges is not None and actual_de != exp_edges:
        log(f"    [yellow]⚠ edge delta: expected {exp_edges:+,}, got {actual_de:+,}[/yellow]")
    return wr
