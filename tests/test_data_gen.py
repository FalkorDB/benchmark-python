"""Tests for data_gen module."""

from benchmark.data_gen import (
    PROPERTY_NAMES,
    TestType,
    generate_node,
    generate_batch,
    build_unwind_query,
    PopulationPlan,
)


def test_property_names_count():
    assert len(PROPERTY_NAMES) == 100


def test_generate_node_has_101_keys():
    """100 properties + id."""
    node = generate_node(42)
    assert node["id"] == 42
    assert len(node) == 101  # 100 props + id


def test_generate_node_with_uuid():
    node = generate_node(42, include_uuid=True)
    assert "uuid" in node
    assert len(node["uuid"]) == 36  # UUID4 string length
    assert len(node) == 102  # 100 props + id + uuid


def test_generate_node_property_types():
    node = generate_node(0)
    # First 40 props are strings
    assert isinstance(node["prop_000"], str)
    # Next 30 are ints (indices 40-69)
    assert isinstance(node["prop_040"], int)
    # Next 20 are floats (indices 70-89)
    assert isinstance(node["prop_070"], float)
    # Last 10 are bools (indices 90-99)
    assert isinstance(node["prop_090"], bool)


def test_generate_batch_size():
    batch = generate_batch(0, 50)
    assert len(batch) == 50
    assert batch[0]["id"] == 0
    assert batch[49]["id"] == 49


def test_generate_batch_with_uuid():
    batch = generate_batch(0, 10, include_uuid=True)
    assert all("uuid" in node for node in batch)
    uuids = [node["uuid"] for node in batch]
    assert len(set(uuids)) == 10  # all unique


def test_build_unwind_query():
    q = build_unwind_query("TestLabel")
    assert "UNWIND $nodes AS node" in q
    assert "CREATE (n:TestLabel {id: node.id})" in q
    assert "n.prop_000 = node.prop_000" in q
    assert "n.prop_099 = node.prop_099" in q
    assert "uuid" not in q


def test_build_unwind_query_with_uuid():
    q = build_unwind_query("TestLabel", include_uuid=True)
    assert "n.uuid = node.uuid" in q


def test_population_plan_batches():
    plan = PopulationPlan(tier_nodes=100, batch_size=30)
    assert plan.num_batches == 4  # ceil(100/30) = 4

    batches = list(plan.iter_batches())
    assert len(batches) == 4
    sizes = [len(b) for _, b in batches]
    assert sizes == [30, 30, 30, 10]
    assert sum(sizes) == 100


def test_population_plan_exact_multiple():
    plan = PopulationPlan(tier_nodes=100, batch_size=50)
    assert plan.num_batches == 2
    batches = list(plan.iter_batches())
    sizes = [len(b) for _, b in batches]
    assert sizes == [50, 50]


def test_population_plan_uuid_type():
    plan = PopulationPlan(tier_nodes=10, batch_size=5, test_type=TestType.UUID)
    assert plan.include_uuid is True
    _, batch = next(plan.iter_batches())
    assert "uuid" in batch[0]


def test_population_plan_baseline_no_uuid():
    plan = PopulationPlan(tier_nodes=10, batch_size=5, test_type=TestType.BASELINE)
    assert plan.include_uuid is False
    _, batch = next(plan.iter_batches())
    assert "uuid" not in batch[0]
