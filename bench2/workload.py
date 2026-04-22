"""The bench2 workloads.

Both queries use UNWIND $ops AS op. The "pair" workload is the focus of
B1 (no index) vs B2 (indexed). The "upsert_label_swap" query reproduces the
customer's reported slow-MERGE pattern (W7a) on the indexed graph.
"""

from __future__ import annotations

import random
from typing import Iterator

from bench2.data import random_props, uuid_for_id

# B1/B2 — pair MERGE: two new :entity:account nodes + connecting edge.
PAIR_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
    "  ON CREATE SET a:account, a.`@type` = 'account', a.id = op.a_id, a += op.a_props "
    "MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
    "  ON CREATE SET b:account, b.`@type` = 'account', b.id = op.b_id, b += op.b_props "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

# Back-compat alias used by init.py.
QUERY = PAIR_QUERY

# B3 — customer (W7a) upsert pattern: single MERGE that ALWAYS runs SET props,
# SET label and REMOVE label, regardless of whether the node was matched or
# created. Reportedly ~9x slower than the FOREACH/CASE workaround.
UPSERT_LABEL_SWAP_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "SET n = op.props "
    "SET n.`@type` = 'account' "
    "SET n:account "
    "REMOVE n:inactive"
)


def make_pair_op(a_id: int, b_id: int, rng: random.Random) -> dict:
    a_hi, a_lo = uuid_for_id(a_id)
    b_hi, b_lo = uuid_for_id(b_id)
    return {
        "a_id": a_id, "a_hi": a_hi, "a_lo": a_lo, "a_props": random_props(rng),
        "b_id": b_id, "b_hi": b_hi, "b_lo": b_lo, "b_props": random_props(rng),
    }


def make_single_op(n_id: int, rng: random.Random) -> dict:
    """Op for the upsert_label_swap (B3) query."""
    hi, lo = uuid_for_id(n_id)
    # SET n = op.props REPLACES all properties; we include the uuid keys so
    # the merged-on identity isn't wiped out. `@type` is set via a separate
    # SET clause in the query (the falkordb-py param serializer chokes on
    # `@`-prefixed keys inside dict params).
    props = random_props(rng)
    props["uuid_hi"] = hi
    props["uuid_lo"] = lo
    props["id"] = n_id
    return {"uuid_hi": hi, "uuid_lo": lo, "props": props}


def iter_batches(
    start_id: int,
    num_pairs: int,
    batch_size: int,
    seed: int = 42,
) -> Iterator[list[dict]]:
    """Yield batches of `batch_size` MERGE-pair ops (B1/B2)."""
    rng = random.Random(seed)
    ops: list[dict] = []
    for k in range(num_pairs):
        a_id = start_id + 2 * k
        b_id = start_id + 2 * k + 1
        ops.append(make_pair_op(a_id, b_id, rng))
        if len(ops) >= batch_size:
            yield ops
            ops = []
    if ops:
        yield ops


def iter_single_batches(
    start_id: int,
    num_ops: int,
    batch_size: int,
    seed: int = 42,
) -> Iterator[list[dict]]:
    """Yield batches of single-node upsert ops (B3)."""
    rng = random.Random(seed)
    ops: list[dict] = []
    for k in range(num_ops):
        ops.append(make_single_op(start_id + k, rng))
        if len(ops) >= batch_size:
            yield ops
            ops = []
    if ops:
        yield ops
