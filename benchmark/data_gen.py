"""Data generator: creates nodes with 100 properties in UNWIND batches."""

from __future__ import annotations

import random
import string
import uuid
from dataclasses import dataclass, field
from enum import Enum


# Property names are fixed — generated once, reused for every node
PROPERTY_NAMES: list[str] = [f"prop_{i:03d}" for i in range(100)]

# Pre-compute which property indices get which type
# 40 strings, 30 ints, 20 floats, 10 bools — deterministic by index
_TYPE_MAP: list[str] = (
    ["string"] * 40 + ["int"] * 30 + ["float"] * 20 + ["bool"] * 10
)


class TestType(str, Enum):
    """The three population test variants."""

    BASELINE = "baseline"        # 100 props, no UUID
    UUID = "uuid"                # 100 props + UUID property
    UUID_INDEXED = "uuid_indexed"  # 100 props + UUID property + index on UUID


def _random_string(length: int = 12) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_node(node_id: int, include_uuid: bool = False) -> dict:
    """Generate a single node dict with 100 properties + an id (+ optional uuid)."""
    props: dict = {"id": node_id}
    if include_uuid:
        props["uuid"] = str(uuid.uuid4())
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


def generate_batch(start_id: int, batch_size: int, include_uuid: bool = False) -> list[dict]:
    """Generate a list of node dicts for a batch."""
    return [generate_node(start_id + i, include_uuid=include_uuid) for i in range(batch_size)]


def build_unwind_query(label: str = "Entity", include_uuid: bool = False) -> str:
    """Return the parameterised UNWIND Cypher query."""
    set_clauses = ", ".join(f"n.{name} = node.{name}" for name in PROPERTY_NAMES)
    if include_uuid:
        set_clauses = f"n.uuid = node.uuid, {set_clauses}"
    return (
        f"UNWIND $nodes AS node "
        f"CREATE (n:{label} {{id: node.id}}) "
        f"SET {set_clauses}"
    )


@dataclass
class PopulationPlan:
    """Describes one tier of the population benchmark."""

    tier_nodes: int
    batch_size: int
    test_type: TestType = TestType.BASELINE
    label: str = "Entity"
    _unwind_query: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._unwind_query = build_unwind_query(
            self.label,
            include_uuid=self.test_type in (TestType.UUID, TestType.UUID_INDEXED),
        )

    @property
    def include_uuid(self) -> bool:
        return self.test_type in (TestType.UUID, TestType.UUID_INDEXED)

    @property
    def num_batches(self) -> int:
        return (self.tier_nodes + self.batch_size - 1) // self.batch_size

    @property
    def query(self) -> str:
        return self._unwind_query

    def iter_batches(self):
        """Yield (batch_index, batch_data) tuples."""
        for i in range(self.num_batches):
            start_id = i * self.batch_size
            actual = min(self.batch_size, self.tier_nodes - start_id)
            yield i, generate_batch(start_id, actual, include_uuid=self.include_uuid)

