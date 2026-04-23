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
    extra_contacts: int = 0,
) -> tuple[int, int]:
    """Drop graph, optionally index, load baseline. Return (nodes, edges).

    If `extra_contacts > 0`, also load that many `:entity:contact` nodes
    into the same composite index. They share the outer `:entity` label
    with the account nodes (so they live in the same `:entity(uuid_hi,
    uuid_lo)` index) but carry the `:contact` inner label instead of
    `:account`. No edges are created among contact nodes.

    The contact uuid range starts at id `2 * (num_nodes // 2) + 1_000_000`
    so it cannot collide with any account node or with the `--start-id`
    typically used by the bench (1M / 2M).
    """

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
        if verbose and batches_done % 5 == 0:
            print(f"[init]   {batches_done * batch_size:,} pairs loaded", flush=True)

    if verbose:
        print(f"[init] adding hub/star edges between existing nodes", flush=True)

    extra_edges = list(hub_star_pairs(num_nodes))
    edge_query = (
        "UNWIND $ops AS op "
        "MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
        "MATCH (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
        "CREATE (a)-[:CONNECTED_TO]->(b)"
    )
    eb_size = 500
    edge_batches_total = (len(extra_edges) + eb_size - 1) // eb_size
    edge_batches_done = 0
    for i in range(0, len(extra_edges), eb_size):
        chunk = extra_edges[i:i + eb_size]
        ops = []
        for hub, spoke in chunk:
            a_hi, a_lo = uuid_for_id(hub)
            b_hi, b_lo = uuid_for_id(spoke)
            ops.append({"a_hi": a_hi, "a_lo": a_lo, "b_hi": b_hi, "b_lo": b_lo})
        client.execute_query(edge_query, params={"ops": ops})
        edge_batches_done += 1
        if verbose and edge_batches_done % 5 == 0:
            print(f"[init]   hub/star {edge_batches_done}/{edge_batches_total} batches "
                  f"({edge_batches_done * eb_size:,} edges)", flush=True)

    nodes, edges = client.graph_size()
    if verbose:
        print(f"[init] done with accounts — graph has {nodes:,} nodes / {edges:,} edges", flush=True)

    if extra_contacts > 0:
        contact_start_id = 2 * num_init_pairs + 1_000_000
        if verbose:
            print(f"[init] loading {extra_contacts:,} :entity:contact nodes "
                  f"(uuid range starts at id {contact_start_id:,})", flush=True)
        contact_query = (
            "UNWIND $ops AS op "
            "MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
            "  ON CREATE SET n:contact, n.`@type` = 'contact', "
            "                n += op.props, n.id = op.id"
        )
        from bench2.workload import iter_single_batches
        c_batches_total = (extra_contacts + batch_size - 1) // batch_size
        c_batches_done = 0
        for ops in iter_single_batches(start_id=contact_start_id, num_ops=extra_contacts,
                                       batch_size=batch_size, seed=2):
            mapped = []
            for op in ops:
                mapped.append({
                    "uuid_hi": op["uuid_hi"],
                    "uuid_lo": op["uuid_lo"],
                    "id": op["props"]["id"],
                    "props": {k: v for k, v in op["props"].items() if k not in ("uuid_hi", "uuid_lo", "id")},
                })
            client.execute_query(contact_query, params={"ops": mapped})
            c_batches_done += 1
            if verbose and c_batches_done % 5 == 0:
                print(f"[init]   contacts {c_batches_done}/{c_batches_total} batches "
                      f"({c_batches_done * batch_size:,} nodes)", flush=True)
        nodes, edges = client.graph_size()
        if verbose:
            print(f"[init] done — graph has {nodes:,} nodes / {edges:,} edges "
                  f"(accounts + {extra_contacts:,} contacts)", flush=True)

    return nodes, edges


def init_graph_add_new_node(
    client: BenchmarkClient,
    num_nodes: int,
    indexed: bool = True,
    batch_size: int = 1000,
    verbose: bool = True,
) -> tuple[int, int]:
    """Init for Test 1 (add_new_node): num_nodes :entity:account 50-prop nodes, no edges.

    Uses the SAME query and op shape as the bench (ADD_NEW_NODE_QUERY) so
    that init writes are byte-for-byte equivalent to bench writes. The
    bench then continues with start_id == num_nodes, producing a
    contiguous uuid range with no overlap.
    """
    from bench2.workload import ADD_NEW_NODE_QUERY, iter_add_new_node_batches

    if verbose:
        print(f"[init] dropping graph '{client._graph_name}'", flush=True)
    client.delete_graph()
    client._graph = client._db.select_graph(client._graph_name)

    if indexed:
        if verbose:
            print(f"[init] creating composite index :entity(uuid_hi, uuid_lo)", flush=True)
        client.create_uuid_pair_index("entity")

    if verbose:
        print(f"[init] loading {num_nodes:,} :entity:account nodes (50 props each, no edges)", flush=True)

    batches_total = (num_nodes + batch_size - 1) // batch_size
    batches_done = 0
    for ops in iter_add_new_node_batches(start_id=0, num_ops=num_nodes,
                                         batch_size=batch_size, seed=1):
        client.execute_query(ADD_NEW_NODE_QUERY, params={"ops": ops})
        batches_done += 1
        if verbose and batches_done % 5 == 0:
            print(f"[init]   {batches_done}/{batches_total} batches "
                  f"({batches_done * batch_size:,} nodes)", flush=True)

    nodes, edges = client.graph_size()
    if verbose:
        print(f"[init] done — graph has {nodes:,} nodes / {edges:,} edges", flush=True)
    return nodes, edges
