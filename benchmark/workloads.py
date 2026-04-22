"""Benchmark workloads — the 6 CRM operation patterns (8 variants w/ MERGE|CREATE axis)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from benchmark.data_gen import _random_props, uuid_for_id


class Workload(str, Enum):
    """6 workloads × MERGE/CREATE axis on W1,W2 = 8 variants."""

    W1_ATTACH_MERGE = "insert_attach_merge"        # new node (MERGE) attached to existing
    W1_ATTACH_CREATE = "insert_attach_create"      # new node (CREATE) attached to existing
    W2_PAIR_MERGE = "insert_pair_merge"            # two new nodes (MERGE both)
    W2_PAIR_CREATE = "insert_pair_create"          # two new nodes (CREATE both)
    W3_EDGE_ONLY = "insert_edge_only"              # edge between two existing
    W4_CDC_PLACEHOLDER = "insert_cdc_placeholder"  # MERGE both w/ :inactive on create
    W5_UPDATE_NODE = "update_node_props"           # SET on existing
    W6_PROMOTE = "promote_inactive"                # :inactive -> :account
    W7_UPSERT_LABEL_SWAP = "upsert_label_swap"     # customer pattern: MERGE + SET label + REMOVE :inactive
    W7_UPSERT_FOREACH = "upsert_label_swap_foreach"  # customer's FOREACH/CASE workaround


# --- Cypher query templates (one row per op via UNWIND) ---

_Q_W1_MERGE = (
    "UNWIND $ops AS op "
    "MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
    "MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
    "  ON CREATE SET b:account, b.`@type` = 'account', b.id = op.b_id, b += op.props "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

_Q_W1_CREATE = (
    "UNWIND $ops AS op "
    "MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
    "CREATE (b:entity:account {uuid_hi: op.b_hi, uuid_lo: op.b_lo, `@type`: 'account', id: op.b_id}) "
    "SET b += op.props "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

_Q_W2_MERGE = (
    "UNWIND $ops AS op "
    "MERGE (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
    "  ON CREATE SET a:account, a.`@type` = 'account', a.id = op.a_id, a += op.a_props "
    "MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
    "  ON CREATE SET b:account, b.`@type` = 'account', b.id = op.b_id, b += op.b_props "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

_Q_W2_CREATE = (
    "UNWIND $ops AS op "
    "CREATE (a:entity:account {uuid_hi: op.a_hi, uuid_lo: op.a_lo, `@type`: 'account', id: op.a_id}) "
    "CREATE (b:entity:account {uuid_hi: op.b_hi, uuid_lo: op.b_lo, `@type`: 'account', id: op.b_id}) "
    "SET a += op.a_props, b += op.b_props "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

_Q_W3 = (
    "UNWIND $ops AS op "
    "MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
    "MATCH (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

_Q_W4 = (
    "UNWIND $ops AS op "
    "MERGE (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo}) "
    "  ON CREATE SET a:inactive, a.`@type` = 'account' "
    "MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo}) "
    "  ON CREATE SET b:inactive, b.`@type` = 'account' "
    "CREATE (a)-[:CONNECTED_TO]->(b)"
)

_Q_W5 = (
    "UNWIND $ops AS op "
    "MATCH (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "SET n += op.new_props"
)

_Q_W6 = (
    "UNWIND $ops AS op "
    "MATCH (n:entity:inactive {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "REMOVE n:inactive SET n:account"
)

# W7 — customer scenario (customer): single-MERGE upsert that unconditionally
# SETs properties, SETs a new label and REMOVEs :inactive. This combines
# the create + update + label-swap path in one statement; on insert it is
# reportedly ~9× slower than on update.
_Q_W7_UPSERT_LABEL_SWAP = (
    "UNWIND $ops AS op "
    "MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "SET n = op.props "
    "SET n:account "
    "REMOVE n:inactive"
)

# W7-foreach — customer's workaround that splits create vs update paths
# via OPTIONAL MATCH + FOREACH/CASE.
_Q_W7_UPSERT_FOREACH = (
    "UNWIND $ops AS op "
    "OPTIONAL MATCH (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) "
    "FOREACH (_ IN CASE WHEN n IS NOT NULL THEN [1] ELSE [] END | "
    "  SET n = op.props SET n:account REMOVE n:inactive) "
    "FOREACH (_ IN CASE WHEN n IS NULL THEN [1] ELSE [] END | "
    "  CREATE (u:entity:account {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) SET u = op.props)"
)


QUERIES: dict[Workload, str] = {
    Workload.W1_ATTACH_MERGE:    _Q_W1_MERGE,
    Workload.W1_ATTACH_CREATE:   _Q_W1_CREATE,
    Workload.W2_PAIR_MERGE:      _Q_W2_MERGE,
    Workload.W2_PAIR_CREATE:     _Q_W2_CREATE,
    Workload.W3_EDGE_ONLY:       _Q_W3,
    Workload.W4_CDC_PLACEHOLDER: _Q_W4,
    Workload.W5_UPDATE_NODE:     _Q_W5,
    Workload.W6_PROMOTE:         _Q_W6,
    Workload.W7_UPSERT_LABEL_SWAP: _Q_W7_UPSERT_LABEL_SWAP,
    Workload.W7_UPSERT_FOREACH:    _Q_W7_UPSERT_FOREACH,
}


@dataclass
class WorkloadSpec:
    """Describes a workload run and yields op batches."""

    workload: Workload
    init_size: int              # graph size before this workload runs
    ops_count: int
    batch_size: int
    seed: int = 42
    # New-id range offset within the shared graph. Suite passes a per-workload offset
    # so W1, W2, W4 don't all try to create nodes with the same uuids.
    id_offset: int = 0

    @property
    def query(self) -> str:
        return QUERIES[self.workload]

    @property
    def num_batches(self) -> int:
        return (self.ops_count + self.batch_size - 1) // self.batch_size

    # --- expected graph deltas (for sanity checks) ---

    @property
    def expected_node_delta(self) -> int | None:
        """Expected post-pre node count delta; None if not predictable (e.g., W4/W6 depend on collisions)."""
        if self.workload in (Workload.W1_ATTACH_MERGE, Workload.W1_ATTACH_CREATE):
            return self.ops_count  # one new node per op
        if self.workload in (Workload.W2_PAIR_MERGE, Workload.W2_PAIR_CREATE):
            return 2 * self.ops_count
        if self.workload == Workload.W3_EDGE_ONLY:
            return 0
        if self.workload == Workload.W5_UPDATE_NODE:
            return 0
        if self.workload == Workload.W6_PROMOTE:
            return 0  # only label changes
        if self.workload in (Workload.W7_UPSERT_LABEL_SWAP, Workload.W7_UPSERT_FOREACH):
            return self.ops_count  # one new node per op
        # W4: new nodes created only if uuid wasn't already present; we pick fresh ids so = 2*ops
        if self.workload == Workload.W4_CDC_PLACEHOLDER:
            return 2 * self.ops_count
        return None

    @property
    def expected_edge_delta(self) -> int | None:
        """All insert workloads add exactly ops_count edges; updates add 0."""
        if self.workload in (Workload.W5_UPDATE_NODE, Workload.W6_PROMOTE,
                             Workload.W7_UPSERT_LABEL_SWAP, Workload.W7_UPSERT_FOREACH):
            return 0
        return self.ops_count

    def iter_batches(
        self,
        existing_inactive_uuids: list[tuple[int, int]] | None = None,
    ) -> Iterator[tuple[int, list[dict]]]:
        """Yield (batch_index, ops_list).

        `existing_inactive_uuids` must be provided for W6 (sampled uuids of :inactive
        nodes in the graph).
        """
        rng = random.Random(self.seed)
        rand_props = random.Random(self.seed + 1)

        # Reserve new-id ranges starting at init_size + id_offset.
        # Separate ranges for A and B where both are new.
        base = self.init_size + self.id_offset
        new_a_start = base
        new_b_start = base + self.ops_count  # only used when A is also new

        for batch_idx in range(self.num_batches):
            start = batch_idx * self.batch_size
            actual = min(self.batch_size, self.ops_count - start)
            ops: list[dict] = []
            for i in range(actual):
                op_idx = start + i
                ops.append(self._build_op(op_idx, rng, rand_props, new_a_start, new_b_start,
                                          existing_inactive_uuids))
            yield batch_idx, ops

    # --- per-op builders ---

    def _random_existing_id(self, rng: random.Random) -> int:
        return rng.randrange(0, self.init_size)

    def _build_op(
        self,
        op_idx: int,
        rng: random.Random,
        rand_props: random.Random,
        new_a_start: int,
        new_b_start: int,
        inactive_pool: list[tuple[int, int]] | None,
    ) -> dict:
        w = self.workload

        if w in (Workload.W1_ATTACH_MERGE, Workload.W1_ATTACH_CREATE):
            a_id = self._random_existing_id(rng)
            b_id = new_a_start + op_idx
            a_hi, a_lo = uuid_for_id(a_id)
            b_hi, b_lo = uuid_for_id(b_id)
            return {
                "a_hi": a_hi, "a_lo": a_lo,
                "b_hi": b_hi, "b_lo": b_lo,
                "b_id": b_id,
                "props": _with_rng(rand_props, _random_props),
            }

        if w in (Workload.W2_PAIR_MERGE, Workload.W2_PAIR_CREATE, Workload.W4_CDC_PLACEHOLDER):
            a_id = new_a_start + op_idx
            b_id = new_b_start + op_idx
            a_hi, a_lo = uuid_for_id(a_id)
            b_hi, b_lo = uuid_for_id(b_id)
            op = {
                "a_hi": a_hi, "a_lo": a_lo,
                "b_hi": b_hi, "b_lo": b_lo,
                "a_id": a_id, "b_id": b_id,
            }
            if w != Workload.W4_CDC_PLACEHOLDER:
                op["a_props"] = _with_rng(rand_props, _random_props)
                op["b_props"] = _with_rng(rand_props, _random_props)
            return op

        if w == Workload.W3_EDGE_ONLY:
            a_id = self._random_existing_id(rng)
            b_id = self._random_existing_id(rng)
            while b_id == a_id:
                b_id = self._random_existing_id(rng)
            a_hi, a_lo = uuid_for_id(a_id)
            b_hi, b_lo = uuid_for_id(b_id)
            return {"a_hi": a_hi, "a_lo": a_lo, "b_hi": b_hi, "b_lo": b_lo}

        if w == Workload.W5_UPDATE_NODE:
            n_id = self._random_existing_id(rng)
            hi, lo = uuid_for_id(n_id)
            return {
                "uuid_hi": hi, "uuid_lo": lo,
                "new_props": _with_rng(rand_props, _random_props),
            }

        if w == Workload.W6_PROMOTE:
            if not inactive_pool:
                raise RuntimeError("W6 requires a populated inactive_pool")
            hi, lo = inactive_pool[op_idx % len(inactive_pool)]
            return {"uuid_hi": hi, "uuid_lo": lo}

        if w in (Workload.W7_UPSERT_LABEL_SWAP, Workload.W7_UPSERT_FOREACH):
            # Customer pattern: each op is an upsert keyed by a uuid in the new range
            # (so first run inserts, re-running on same range would be all updates).
            n_id = new_a_start + op_idx
            hi, lo = uuid_for_id(n_id)
            return {
                "uuid_hi": hi, "uuid_lo": lo,
                "props": _with_rng(rand_props, _random_props),
            }

        raise ValueError(f"unknown workload {w}")


def _with_rng(rng: random.Random, fn):
    """Invoke a random-using function with a scoped RNG (swap module-level random)."""
    import random as _r
    saved = _r.random, _r.randint, _r.uniform, _r.choice, _r.choices
    _r.random = rng.random
    _r.randint = rng.randint
    _r.uniform = rng.uniform
    _r.choice = rng.choice
    _r.choices = rng.choices
    try:
        return fn()
    finally:
        _r.random, _r.randint, _r.uniform, _r.choice, _r.choices = saved
