"""Phase 1: idempotent init graph loader."""

from __future__ import annotations

import sys
import time

from benchmark.data_gen import (
    ENTITY_LABEL, PopulationPlan, TestType,
    generate_batch, generate_edges_for_batch,
)
from benchmark.falkor_client import BenchmarkClient

_LOG_PCT = 0.05  # progress log every 5%


def graph_name_for(size: int, indexed: bool) -> str:
    """Canonical name for an init graph."""
    suffix = "" if indexed else "_noindex"
    return f"crm_init_{size}{suffix}"


def ensure_init(
    host: str,
    port: int,
    size: int,
    indexed: bool = True,
    batch_size: int = 1000,
    force: bool = False,
    username: str | None = None,
    password: str | None = None,
    log=print,
    throttle_ms: float = 0.0,
) -> BenchmarkClient:
    """Ensure a graph of `size` :entity:account nodes + edges exists.

    Returns a BenchmarkClient already pointed at that graph.
    If graph already has the expected node count and `force=False`, skip loading.
    """
    name = graph_name_for(size, indexed)
    client = BenchmarkClient(
        host=host, port=port, graph_name=name,
        username=username, password=password,
    )

    if not force:
        existing_nodes, existing_edges = client.graph_size()
        if existing_nodes == size:
            log(f"  ✓ init graph '{name}' already present ({existing_nodes:,} nodes, "
                f"{existing_edges:,} edges) — reusing")
            return client
        if existing_nodes > 0:
            log(f"  ⚠ init graph '{name}' has {existing_nodes:,} nodes (expected {size:,}); "
                f"rebuilding")

    client.delete_graph()
    if indexed:
        client.create_uuid_pair_index(ENTITY_LABEL)

    test_type = TestType.MERGE_INDEXED if indexed else TestType.MERGE_BASELINE
    plan = PopulationPlan(tier_nodes=size, batch_size=batch_size, test_type=test_type)

    log(f"  loading '{name}': {size:,} nodes, batch={batch_size:,}, "
        f"indexed={indexed}...")
    start = time.perf_counter()
    log_every = max(1, int(plan.num_batches * _LOG_PCT))

    for i in range(plan.num_batches):
        start_id = i * batch_size
        actual = min(batch_size, size - start_id)
        nodes = generate_batch(start_id, actual)
        edges = generate_edges_for_batch(nodes)
        result = client.execute_query(
            plan.combined_query,
            params={"nodes": nodes, "edges": edges},
        )
        if not result.success:
            raise RuntimeError(f"init batch {i} failed: {result.error}")
        del nodes, edges
        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)
        if (i + 1) % log_every == 0 or i + 1 == plan.num_batches:
            done = min((i + 1) * batch_size, size)
            log(f"    {done:,}/{size:,}  ({time.perf_counter() - start:.1f}s)")
            sys.stdout.flush()

    elapsed = time.perf_counter() - start
    nodes_actual, edges_actual = client.graph_size()
    log(f"  ✓ '{name}' loaded in {elapsed:.1f}s "
        f"({nodes_actual:,} nodes, {edges_actual:,} edges)")
    return client
