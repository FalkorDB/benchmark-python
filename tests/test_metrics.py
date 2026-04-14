"""Tests for metrics module."""

from benchmark.metrics import MetricsCollector, BenchmarkResult


def test_metrics_collector_basic():
    mc = MetricsCollector(tier_nodes=100, batch_size=50)
    mc.start()
    mc.record_batch(0, 50, 10.5, True)
    mc.record_batch(1, 50, 12.3, True)
    result = mc.finish()

    assert result.tier_nodes == 100
    assert result.batch_size == 50
    assert result.success_count == 2
    assert result.error_count == 0
    assert result.total_time_s > 0
    assert result.nodes_per_sec > 0
    assert result.p50_ms > 0


def test_metrics_collector_with_errors():
    mc = MetricsCollector(tier_nodes=100, batch_size=50)
    mc.start()
    mc.record_batch(0, 50, 10.0, True)
    mc.record_batch(1, 50, 999.0, False, error="connection lost")
    result = mc.finish()

    assert result.success_count == 1
    assert result.error_count == 1


def test_benchmark_result_to_dict():
    mc = MetricsCollector(tier_nodes=50, batch_size=25)
    mc.start()
    mc.record_batch(0, 25, 5.0, True)
    mc.record_batch(1, 25, 6.0, True)
    tier = mc.finish()

    br = BenchmarkResult(tiers=[tier])
    d = br.to_dict()

    assert len(d["tiers"]) == 1
    assert d["tiers"][0]["tier_nodes"] == 50
    assert "nodes_per_sec" in d["tiers"][0]
    assert "p99_ms" in d["tiers"][0]
