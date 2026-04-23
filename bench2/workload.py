"""The bench2 workloads.

Both queries use UNWIND $ops AS op. The "pair" workload is the focus of
B1 (no index) vs B2 (indexed). The "upsert_label_swap" query reproduces the
customer's reported slow-MERGE pattern (W7a) on the indexed graph.
"""

from __future__ import annotations

import random
import time
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

# B5 — FOREACH/CASE workaround for W7a. Same semantics as B3 but:
#   * ON CREATE SET only fires on newly-created nodes (sets label, @type, props)
#   * FOREACH+CASE branches only run if the row actually carries :inactive
#     (i.e. the REMOVE only executes when there's something to remove)
# This skips the redundant writes that B3 performs on every match.
UPSERT_FOREACH_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "  ON CREATE SET n:account, n.`@type` = 'account', n += op.props "
    "FOREACH (_ IN CASE WHEN n:inactive THEN [1] ELSE [] END | "
    "  REMOVE n:inactive SET n:account)"
)


# Test 1 (add_new_node) — single MERGE on the composite uuid key, 50-prop
# CRM-shaped record, two labels (:entity:account). MERGE always takes the
# create branch (every uuid is fresh). ON CREATE SET writes the entire
# 50-prop bag in one shot.
ADD_NEW_NODE_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity:account {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "  ON CREATE SET n = op.props"
)


# Test 2 (add_new_node_with_audit) — same MERGE shape as Test 1, plus two
# audit SETs after the merge: updated_at (assigned) and version
# (read-then-write via coalesce). Measures the marginal cost of two extra
# SET clauses on top of the create-branch MERGE.
ADD_NEW_NODE_WITH_AUDIT_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity:account {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "  ON CREATE SET n = op.props "
    "SET n.updated_at = op.updated_at "
    "SET n.version = coalesce(n.version, 0) + 1"
)


# Test 3 (upsert_w7) — the customer-reported W7 upsert pattern, run at
# the Test 1/2 50-prop scale and tier ladder. Differences from Test 1:
#   * MERGE matches on :entity ONLY; :account is added after via SET label
#   * All 50 props are rewritten UNCONDITIONALLY via `SET n = op.props`
#     (no ON CREATE/ON MATCH split)
#   * `SET n:account` and `REMOVE n:inactive` are unconditional label ops
# Op shape is identical to Test 1 (uuid_hi, uuid_lo, 50-prop bag), so we
# reuse iter_add_new_node_batches.
UPSERT_W7_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "SET n = op.props "
    "SET n:account "
    "REMOVE n:inactive"
)


# Test 4 init query — fast lean MERGE that produces the SAME node shape
# as UPSERT_W7_ACTIVE_QUERY would (50 props + active=true,
# :entity:account labels) but using ON CREATE SET so init is fast like
# Test 1. The bench then uses UPSERT_W7_ACTIVE_QUERY against the
# resulting graph, so what we measure is the bench query, not init.
ADD_NEW_NODE_ACTIVE_INIT_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity:account {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "  ON CREATE SET n = op.props, n.active = true"
)


# Test 4 (upsert_w7_active) — same as Test 3 but the `:inactive` label
# swap is replaced with a boolean `active` property assignment. Requires
# a property index on :entity(active) created at init time. Isolates the
# cost contribution of the `REMOVE n:inactive` label op vs an equivalent
# property write.
UPSERT_W7_ACTIVE_QUERY = (
    "UNWIND $ops AS op "
    "MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "SET n = op.props "
    "SET n:account "
    "SET n.active = true"
)


# Test 5 (delete_by_uuid) — single-node delete via composite uuid index.
# Pure index lookup + node delete, no edges (init shape has none, so plain
# DELETE suffices — no DETACH needed). Op shape is just the uuid pair.
DELETE_BY_UUID_QUERY = (
    "UNWIND $ops AS op "
    "MATCH (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "DELETE n"
)


def make_delete_op(n_id: int) -> dict:
    """Op for Test 5: just the composite uuid identifying the node to delete."""
    hi, lo = uuid_for_id(n_id)
    return {"uuid_hi": hi, "uuid_lo": lo}


def iter_delete_batches(
    start_id: int,
    num_ops: int,
    batch_size: int,
    seed: int = 42,
) -> Iterator[list[dict]]:
    """Yield batches of single-node delete ops (Test 5).

    seed is accepted for signature parity with the other iter_*_batches
    functions but unused — delete ops are deterministic from start_id.
    """
    del seed
    ops: list[dict] = []
    for k in range(num_ops):
        ops.append(make_delete_op(start_id + k))
        if len(ops) >= batch_size:
            yield ops
            ops = []
    if ops:
        yield ops


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


def make_add_new_node_op(n_id: int, rng: random.Random) -> dict:
    """Op for the add_new_node (Test 1) query: 50-prop :entity:account record."""
    from bench2.data import random_props_50
    hi, lo = uuid_for_id(n_id)
    props = random_props_50(rng)
    props["uuid_hi"] = hi
    props["uuid_lo"] = lo
    return {"uuid_hi": hi, "uuid_lo": lo, "props": props}


def iter_add_new_node_batches(
    start_id: int,
    num_ops: int,
    batch_size: int,
    seed: int = 42,
) -> Iterator[list[dict]]:
    """Yield batches of single-node 50-prop add_new_node ops (Test 1)."""
    rng = random.Random(seed)
    ops: list[dict] = []
    for k in range(num_ops):
        ops.append(make_add_new_node_op(start_id + k, rng))
        if len(ops) >= batch_size:
            yield ops
            ops = []
    if ops:
        yield ops


def make_add_new_node_with_audit_op(n_id: int, rng: random.Random) -> dict:
    """Op for Test 2: same as Test 1 plus an updated_at timestamp."""
    op = make_add_new_node_op(n_id, rng)
    op["updated_at"] = int(time.time() * 1000)
    return op


def iter_add_new_node_with_audit_batches(
    start_id: int,
    num_ops: int,
    batch_size: int,
    seed: int = 42,
) -> Iterator[list[dict]]:
    """Yield batches of audit-stamped 50-prop add_new_node ops (Test 2)."""
    rng = random.Random(seed)
    ops: list[dict] = []
    for k in range(num_ops):
        ops.append(make_add_new_node_with_audit_op(start_id + k, rng))
        if len(ops) >= batch_size:
            yield ops
            ops = []
    if ops:
        yield ops
