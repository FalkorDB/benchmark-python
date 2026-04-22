"""Init: drop graph, optionally create index, load baseline via MERGE-pair.

Init shape: 100K :entity:account nodes with hub/star edges (every 10th node
is a hub linked to the next 9 = ~90K edges, ~1 edge/node).

Init writes use the SAME MERGE-pair query as the measured benchmark, applied
to a pre-allocated id range [0 .. 2*num_init_pairs). For the hub/star edges
we use a separate small step after MERGE seeding the nodes. To keep things
simple AND match the workload pattern, init does:

  1. (optional) CREATE INDEX :entity(uuid_hi, uuid_lo)
  2. MERGE-pair the first num_init_pairs sequential pairs (same Cypher as
     the benchmark). Each pair creates 2 nodes + 1 edge. With num_init_pairs
     = 50_000 we get 100K nodes and 50K initial edges.
  3. Add the remaining hub/star edges so total edges ~= 90K (matches the
     declared ~1 edge/node target). Each extra edge connects two existing
     nodes via the same MERGE pattern (degenerate "MERGE existing" path).

This keeps init's per-write Cypher == the benchmark's per-write Cypher.
"""

from __future__ import annotations

from benchmark.falkor_client import BenchmarkClient
from bench2.data import hub_star_pairs, uuid_for_id
from bench2.workload import QUERY, iter_batches


def init_graph(
    client: BenchmarkClient,
    num_nodes: int = 100_000,
    indexed: bool = True,
    batch_size: int = 100,
    verbose: bool = True,
) -> tuple[int, int]:
    """Drop graph, optionally index, load baseline. Return (nodes, edges)."""

    if verbose:
        print(f"[init] dropping graph '{client._graph_name}'")
    client.delete_graph()
    client._graph = client._db.select_graph(client._graph_name)

    if indexed:
        if verbose:
            print(f"[init] creating composite index :entity(uuid_hi, uuid_lo)")
        client.create_uuid_pair_index("entity")

    num_init_pairs = num_nodes // 2  # 50_000 pairs = 100_000 nodes
    if verbose:
        print(f"[init] loading {num_init_pairs:,} MERGE-pairs ({num_nodes:,} nodes, {num_init_pairs:,} edges)")

    batches_done = 0
    for ops in iter_batches(start_id=0, num_pairs=num_init_pairs, batch_size=batch_size, seed=1):
        client.execute_query(QUERY, params={"ops": ops})
        batches_done += 1
        if verbose and batches_done % 50 == 0:
            print(f"[init]   {batches_done * batch_size:,} pairs loaded")

    if verbose:
        print(f"[init] adding hub/star edges between existing nodes")

    extra_edges = list(hub_star_pairs(num_nodes))
    edge_query = (
        "UNWIND $ops AS op "
        "MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
        "MATCH (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
        "CREATE (a)-[:CONNECTED_TO]->(b)"
    )
    eb_size = 500
    for i in range(0, len(extra_edges), eb_size):
        chunk = extra_edges[i:i + eb_size]
        ops = []
        for hub, spoke in chunk:
            a_hi, a_lo = uuid_for_id(hub)
            b_hi, b_lo = uuid_for_id(spoke)
            ops.append({"a_hi": a_hi, "a_lo": a_lo, "b_hi": b_hi, "b_lo": b_lo})
        client.execute_query(edge_query, params={"ops": ops})

    nodes, edges = client.graph_size()
    if verbose:
        print(f"[init] done — graph has {nodes:,} nodes / {edges:,} edges")
    return nodes, edges
