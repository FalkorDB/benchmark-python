"""Data generator (CRM-aligned): nodes carry :entity + :account, numeric UUID, MERGE flow."""

from __future__ import annotations

import hashlib
import itertools
import random
import string
import uuid
from dataclasses import dataclass, field
from enum import Enum


PROPERTY_NAMES: list[str] = [f"prop_{i:03d}" for i in range(100)]

_TYPE_MAP: list[str] = (
    ["string"] * 40 + ["int"] * 30 + ["float"] * 20 + ["bool"] * 10
)

GROUP_SIZE = 5
EDGES_PER_GROUP = 10  # C(5,2)

PRIMARY_LABEL = "account"
PRIMARY_TYPE = "account"
ENTITY_LABEL = "entity"
INACTIVE_LABEL = "inactive"


class TestType(str, Enum):
    """CRM-aligned population variants. All use :entity + :account + numeric UUID + edges.

    Every batch creates its nodes AND their edges in a single Cypher round-trip.
    Edges follow the existing rule: every 5 consecutive nodes form an all-pairs subgraph
    (10 directed edges per group of 5).
    """

    MERGE_BASELINE = "merge_baseline"     # MERGE :entity:account + edges, NO uuid index
    MERGE_INDEXED = "merge_indexed"       # MERGE :entity:account + edges, with range index
    INACTIVE_FLOW = "inactive_flow"       # two-phase merge (inactive -> account) + edges, indexed


_INDEXED_TYPES = {TestType.MERGE_INDEXED, TestType.INACTIVE_FLOW}
_TWO_PHASE_TYPES = {TestType.INACTIVE_FLOW}


_UINT64 = 1 << 64
_UINT63 = 1 << 63


def _to_signed64(x: int) -> int:
    return x - _UINT64 if x >= _UINT63 else x


def generate_uuid_pair() -> tuple[int, int]:
    """Generate a 128-bit UUID and split it into two signed-int64 halves (non-deterministic)."""
    u = uuid.uuid4().int
    return _to_signed64(u >> 64), _to_signed64(u & ((1 << 64) - 1))


# --- Deterministic UUID derivation for init/workload reproducibility ---
#
# SHA-256 over a 4-byte namespace tag + 8-byte big-endian node id.
# First 16 bytes of the digest form the uuid; split into two signed int64 halves.
# Namespace tag lets us support multiple independent id spaces later (e.g., contact vs
# account pools) without collision — currently always "ent0".

_UUID_NS = b"ent0"


def uuid_for_id(node_id: int) -> tuple[int, int]:
    """Deterministic (uuid_hi, uuid_lo) pair for a given node id.

    Same input id always yields the same pair. Used by init (to seed the graph) and by
    benchmark workloads (to compute an existing node's uuid without reading from the DB).
    """
    h = hashlib.sha256(_UUID_NS + node_id.to_bytes(8, "big", signed=False)).digest()
    hi = int.from_bytes(h[0:8], "big", signed=False)
    lo = int.from_bytes(h[8:16], "big", signed=False)
    return _to_signed64(hi), _to_signed64(lo)


def _random_string(length: int = 12) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def _random_props() -> dict:
    """Generate the 100 random property values for a node."""
    props: dict = {}
    for idx, name in enumerate(PROPERTY_NAMES):
        t = _TYPE_MAP[idx]
        if t == "string":
            props[name] = _random_string()
        elif t == "int":
            props[name] = random.randint(0, 1_000_000)
        elif t == "float":
            props[name] = round(random.uniform(0.0, 1_000_000.0), 4)
        else:
            props[name] = random.choice([True, False])
    return props


def generate_node(node_id: int, deterministic_uuid: bool = True) -> dict:
    """Generate one batch entry: numeric UUID pair + props bag.

    Returned shape matches the parameterised UNWIND queries:
        {"id": int, "uuid_hi": int64, "uuid_lo": int64, "props": {...100 props...}}

    deterministic_uuid=True (default, new code path): uuid derived from node_id via
    SHA-256, so phase-2 benchmarks can reconstruct the uuid of any existing node.
    deterministic_uuid=False: legacy random uuid via uuid.uuid4() (used only by the
    deprecated `populate` command for back-compat).
    """
    if deterministic_uuid:
        hi, lo = uuid_for_id(node_id)
    else:
        hi, lo = generate_uuid_pair()
    return {
        "id": node_id,
        "uuid_hi": hi,
        "uuid_lo": lo,
        "props": _random_props(),
    }


def generate_batch(start_id: int, batch_size: int, deterministic_uuid: bool = True) -> list[dict]:
    return [generate_node(start_id + i, deterministic_uuid=deterministic_uuid) for i in range(batch_size)]


def generate_edges_for_batch(nodes: list[dict]) -> list[dict]:
    """Generate edges from a batch of nodes (10 edges per 5 consecutive nodes).

    Edges reference nodes by their (uuid_hi, uuid_lo) so they don't depend on `id`.
    """
    edges: list[dict] = []
    for group_start in range(0, len(nodes), GROUP_SIZE):
        group = nodes[group_start:group_start + GROUP_SIZE]
        if len(group) < 2:
            continue
        for a, b in itertools.combinations(group, 2):
            edges.append({
                "src_hi": a["uuid_hi"], "src_lo": a["uuid_lo"],
                "dst_hi": b["uuid_hi"], "dst_lo": b["uuid_lo"],
            })
    return edges


def build_combined_query(two_phase: bool) -> str:
    """Single Cypher query that creates nodes AND their edges in one round-trip.

    Single-phase: MERGE node directly with :account label.
    Two-phase: MERGE node with :inactive on create, then promote to :account in same query.

    Edges in $edges are matched by (uuid_hi, uuid_lo) and connected with :CONNECTED_TO.
    """
    if two_phase:
        node_section = (
            "UNWIND $nodes AS node "
            "MERGE (n:entity {uuid_hi: node.uuid_hi, uuid_lo: node.uuid_lo}) "
            "ON CREATE SET n:inactive, n.`@type` = 'account', n.id = node.id, n += node.props "
            "WITH count(n) AS _phase1 "
            "UNWIND $nodes AS p "
            "MERGE (m:entity {uuid_hi: p.uuid_hi, uuid_lo: p.uuid_lo}) "
            "REMOVE m:inactive SET m:account "
            "WITH count(m) AS _phase2 "
        )
    else:
        node_section = (
            "UNWIND $nodes AS node "
            "MERGE (n:entity {uuid_hi: node.uuid_hi, uuid_lo: node.uuid_lo}) "
            "ON CREATE SET n:account, n.`@type` = 'account', n.id = node.id, n += node.props "
            "WITH count(n) AS _phase1 "
        )
    edge_section = (
        "UNWIND $edges AS edge "
        "MATCH (a:entity {uuid_hi: edge.src_hi, uuid_lo: edge.src_lo}), "
        "(b:entity {uuid_hi: edge.dst_hi, uuid_lo: edge.dst_lo}) "
        "CREATE (a)-[:CONNECTED_TO]->(b)"
    )
    return node_section + edge_section


@dataclass
class PopulationPlan:
    """Describes one tier of the CRM-aligned population benchmark."""

    tier_nodes: int
    batch_size: int
    test_type: TestType = TestType.MERGE_BASELINE
    label: str = ENTITY_LABEL  # kept for back-compat; entity label is fixed

    _combined_query: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._combined_query = build_combined_query(
            two_phase=self.test_type in _TWO_PHASE_TYPES,
        )

    @property
    def needs_uuid_index(self) -> bool:
        return self.test_type in _INDEXED_TYPES

    @property
    def two_phase(self) -> bool:
        return self.test_type in _TWO_PHASE_TYPES

    @property
    def num_batches(self) -> int:
        return (self.tier_nodes + self.batch_size - 1) // self.batch_size

    @property
    def combined_query(self) -> str:
        return self._combined_query

    def iter_batches(self):
        """Yield (batch_index, nodes, edges) tuples. Edges are always present."""
        for i in range(self.num_batches):
            start_id = i * self.batch_size
            actual = min(self.batch_size, self.tier_nodes - start_id)
            nodes = generate_batch(start_id, actual)
            edges = generate_edges_for_batch(nodes)
            yield i, nodes, edges
