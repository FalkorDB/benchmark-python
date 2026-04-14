"""Metrics collection: per-tier batch latencies, throughput."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BatchMetric:
    """Recorded result of one batch insert."""

    batch_index: int
    batch_size: int
    duration_ms: float
    success: bool
    error: str | None = None


@dataclass
class TierResult:
    """Aggregated results for one population tier."""

    tier_nodes: int
    batch_size: int
    test_type: str
    total_time_s: float
    batches: list[BatchMetric] = field(default_factory=list)

    # computed after collection
    nodes_per_sec: float = 0.0
    avg_batch_ms: float = 0.0
    success_count: int = 0
    error_count: int = 0

    def compute(self) -> None:
        """Compute aggregate stats from batch metrics."""
        if not self.batches:
            return

        durations = [b.duration_ms for b in self.batches]
        self.avg_batch_ms = sum(durations) / len(durations)
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
class BenchmarkResult:
    """Full benchmark result across all tiers."""

    tiers: list[TierResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tiers": [t.to_dict() for t in self.tiers],
        }


class MetricsCollector:
    """Collects batch metrics for a single tier run."""

    def __init__(self, tier_nodes: int, batch_size: int, test_type: str = "baseline") -> None:
        self.tier_nodes = tier_nodes
        self.batch_size = batch_size
        self.test_type = test_type
        self._batches: list[BatchMetric] = []
        self._start: float = 0.0

    def start(self) -> None:
        self._start = time.perf_counter()

    def record_batch(self, batch_index: int, batch_size: int, duration_ms: float, success: bool, error: str | None = None) -> None:
        self._batches.append(
            BatchMetric(
                batch_index=batch_index,
                batch_size=batch_size,
                duration_ms=duration_ms,
                success=success,
                error=error,
            )
        )

    def finish(self) -> TierResult:
        total_time = time.perf_counter() - self._start
        result = TierResult(
            tier_nodes=self.tier_nodes,
            batch_size=self.batch_size,
            test_type=self.test_type,
            total_time_s=total_time,
            batches=self._batches,
        )
        result.compute()
        return result
