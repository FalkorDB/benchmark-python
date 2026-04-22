"""Metrics: per-batch latencies with percentile aggregation for workload runs."""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field


@dataclass
class BatchMetric:
    batch_index: int
    batch_size: int
    duration_ms: float
    success: bool
    error: str | None = None
    # Kept for back-compat with the deprecated `populate` command:
    merge_ms: float = 0.0
    promote_ms: float = 0.0
    edge_ms: float = 0.0


@dataclass
class TierResult:
    """Aggregated results for one `populate` tier (back-compat)."""

    tier_nodes: int
    batch_size: int
    test_type: str
    total_time_s: float
    batches: list[BatchMetric] = field(default_factory=list)

    nodes_per_sec: float = 0.0
    avg_batch_ms: float = 0.0
    success_count: int = 0
    error_count: int = 0

    def compute(self) -> None:
        if not self.batches:
            return
        self.avg_batch_ms = sum(b.duration_ms for b in self.batches) / len(self.batches)
        self.success_count = sum(1 for b in self.batches if b.success)
        self.error_count = sum(1 for b in self.batches if not b.success)
        if self.total_time_s > 0:
            self.nodes_per_sec = self.tier_nodes / self.total_time_s

    def to_dict(self) -> dict:
        return {
            "test_type": self.test_type,
            "tier_nodes": self.tier_nodes,
            "batch_size": self.batch_size,
            "total_time_s": round(self.total_time_s, 3),
            "nodes_per_sec": round(self.nodes_per_sec, 1),
            "avg_batch_ms": round(self.avg_batch_ms, 2),
            "success_batches": self.success_count,
            "error_batches": self.error_count,
            "total_batches": len(self.batches),
        }


@dataclass
class WorkloadResult:
    """Results for one workload run (phase-2 benchmark output)."""

    workload: str          # e.g. "insert_attach_merge"
    tier_nodes: int        # init graph size
    indexed: bool
    ops_count: int
    batch_size: int
    total_time_s: float
    batches: list[BatchMetric] = field(default_factory=list)

    # Sanity-check deltas
    pre_nodes: int = 0
    post_nodes: int = 0
    pre_edges: int = 0
    post_edges: int = 0

    # Headline metrics (5)
    ops_per_sec: float = 0.0
    avg_batch_ms: float = 0.0
    p95_batch_ms: float = 0.0
    error_count: int = 0

    # Deep-dive metrics (not in headline table; in JSON only)
    p50_batch_ms: float = 0.0
    p99_batch_ms: float = 0.0
    min_batch_ms: float = 0.0
    max_batch_ms: float = 0.0
    success_count: int = 0

    def compute(self) -> None:
        if not self.batches:
            return
        durations = sorted(b.duration_ms for b in self.batches)
        self.avg_batch_ms = statistics.fmean(durations)
        self.min_batch_ms = durations[0]
        self.max_batch_ms = durations[-1]
        self.p50_batch_ms = _percentile(durations, 0.50)
        self.p95_batch_ms = _percentile(durations, 0.95)
        self.p99_batch_ms = _percentile(durations, 0.99)
        self.success_count = sum(1 for b in self.batches if b.success)
        self.error_count = len(self.batches) - self.success_count
        if self.total_time_s > 0:
            self.ops_per_sec = self.ops_count / self.total_time_s

    def to_dict(self) -> dict:
        return {
            "workload": self.workload,
            "tier_nodes": self.tier_nodes,
            "indexed": self.indexed,
            "ops_count": self.ops_count,
            "batch_size": self.batch_size,
            "total_time_s": round(self.total_time_s, 3),
            "ops_per_sec": round(self.ops_per_sec, 1),
            "avg_batch_ms": round(self.avg_batch_ms, 3),
            "p50_batch_ms": round(self.p50_batch_ms, 3),
            "p95_batch_ms": round(self.p95_batch_ms, 3),
            "p99_batch_ms": round(self.p99_batch_ms, 3),
            "min_batch_ms": round(self.min_batch_ms, 3),
            "max_batch_ms": round(self.max_batch_ms, 3),
            "success_batches": self.success_count,
            "error_batches": self.error_count,
            "total_batches": len(self.batches),
            "pre_nodes": self.pre_nodes,
            "post_nodes": self.post_nodes,
            "pre_edges": self.pre_edges,
            "post_edges": self.post_edges,
            "delta_nodes": self.post_nodes - self.pre_nodes,
            "delta_edges": self.post_edges - self.pre_edges,
        }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile on a pre-sorted list. q in [0, 1]."""
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[k]


@dataclass
class BenchmarkResult:
    """Container for a mixed run — tier results (from populate) or workload results (suite)."""

    tiers: list[TierResult] = field(default_factory=list)
    workloads: list[WorkloadResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tiers": [t.to_dict() for t in self.tiers],
            "workloads": [w.to_dict() for w in self.workloads],
        }


class MetricsCollector:
    """Generic collector. Used by both the `populate` (back-compat) and workload runners."""

    def __init__(self, label: str, total_units: int, batch_size: int) -> None:
        self.label = label
        self.total_units = total_units  # total nodes (tier) or total ops (workload)
        self.batch_size = batch_size
        self._batches: list[BatchMetric] = []
        self._start: float = 0.0

    def start(self) -> None:
        self._start = time.perf_counter()

    def record_batch(
        self,
        batch_index: int,
        batch_size: int,
        duration_ms: float,
        success: bool,
        error: str | None = None,
        merge_ms: float = 0.0,
        promote_ms: float = 0.0,
        edge_ms: float = 0.0,
    ) -> None:
        self._batches.append(
            BatchMetric(
                batch_index=batch_index,
                batch_size=batch_size,
                duration_ms=duration_ms,
                success=success,
                error=error,
                merge_ms=merge_ms,
                promote_ms=promote_ms,
                edge_ms=edge_ms,
            )
        )

    def total_time_s(self) -> float:
        return time.perf_counter() - self._start

    @property
    def batches(self) -> list[BatchMetric]:
        return self._batches
