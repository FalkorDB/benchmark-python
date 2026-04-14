"""Tests for data_gen module."""

from benchmark.data_gen import (
    PROPERTY_NAMES,
    TestType,
    generate_node,
    generate_batch,
    generate_edges_for_batch,
    build_unwind_query,
    build_edge_query,
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
    assert len(node["uuid"]) == 36
    assert len(node) == 102  # 100 props + id + uuid


def test_generate_node_property_types():
    node = generate_node(0)
    assert isinstance(node["prop_000"], str)
    assert isinstance(node["prop_040"], int)
    assert isinstance(node["prop_070"], float)
    assert isinstance(node["prop_090"], bool)


def test_generate_batch_size():
    batch = generate_batch(0, 50)
    assert len(batch) == 50
    assert batch[0]["id"] == 0
    assert batch[49]["id"] == 49


def test_generate_batch_with_uuid():
    batch = generate_batch(0, 10, include_uuid=True)
    assert all("uuid" in node for node in batch)
    assert len(set(n["uuid"] for n in batch)) == 10


def test_generate_edges_for_batch():
    edges = generate_edges_for_batch(0, 10)
    # 2 groups of 5 -> C(5,2)*2 = 20
    assert len(edges) == 20
    assert all("src" in e and "dst" in e for e in edges)


def test_generate_edges_partial_group():
    # 7 nodes: group of 5 (10 edges) + group of 2 (1 edge) = 11
    edges = generate_edges_for_batch(0, 7)
    assert len(edges) == 11


def test_generate_edges_single_node():
    edges = generate_edges_for_batch(0, 1)
    assert len(edges) == 0


def test_build_unwind_query():
    q = build_unwind_query("TestLabel")
    assert "UNWIND $nodes AS node" in q
    assert "CREATE (n:TestLabel {id: node.id})" in q
    assert "uuid" not in q


def test_build_unwind_query_with_uuid():
    q = build_unwind_query("TestLabel", include_uuid=True)
    assert "n.uuid = node.uuid" in q


def test_build_edge_query():
    q = build_edge_query("TestLabel")
    assert "UNWIND $edges AS edge" in q
    assert "MATCH (a:TestLabel {id: edge.src})" in q
    assert "CREATE (a)-[:CONNECTED_TO]->(b)" in q


def test_population_plan_batches():
    plan = PopulationPlan(tier_nodes=100, batch_size=30)
    assert plan.num_batches == 4
    batches = list(plan.iter_batches())
    assert len(batches) == 4
    sizes = [len(nodes) for _, nodes, _ in batches]
    assert sizes == [30, 30, 30, 10]


def test_population_plan_baseline_no_edges():
    plan = PopulationPlan(tier_nodes=10, batch_size=5, test_type=TestType.BASELINE)
    assert plan.include_edges is False
    _, nodes, edges = next(plan.iter_batches())
    assert "uuid" not in nodes[0]
    assert edges is None


def test_population_plan_uuid_edges():
    plan = PopulationPlan(tier_nodes=10, batch_size=5, test_type=TestType.UUID_EDGES)
    assert plan.include_uuid is True
    assert plan.include_edges is True
    _, nodes, edges = next(plan.iter_batches())
    assert "uuid" in nodes[0]
    assert len(edges) == 10  # C(5,2)


def test_population_plan_uuid_indexed_edges():
    plan = PopulationPlan(tier_nodes=10, batch_size=5, test_type=TestType.UUID_INDEXED_EDGES)
    assert plan.needs_uuid_index is True
    assert plan.include_edges is True
