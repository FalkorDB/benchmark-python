"""Measured benchmark loop. Discards warm-up batches, returns per-op latencies."""

from __future__ import annotations

import time
from dataclasses import dataclass

from benchmark.falkor_client import BenchmarkClient
from bench2.workload import PAIR_QUERY as QUERY, iter_batches


@dataclass
class RunResult:
    benchmark: str
    indexed: bool
    ops: int
    batch_size: int
    total_s: float
    ops_per_sec: float
    per_op_avg_ms: float
    per_op_p50_ms: float
    per_op_p95_ms: float
    per_op_p99_ms: float
    per_op_min_ms: float
    per_op_max_ms: float
    success_batches: int
    error_batches: int
    warmup_batches: int


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def run_benchmark(
    client: BenchmarkClient,
    name: str,
    indexed: bool,
    start_id: int,
    num_pairs: int = 25_000,
    batch_size: int = 100,
    warmup_batches: int = 10,
    seed: int = 42,
    verbose: bool = True,
    query: str | None = None,
    iter_fn=None,
) -> RunResult:
    """Run num_pairs MERGE ops in batches; discard first `warmup_batches`.

    By default uses the pair-MERGE workload (B1/B2). Pass `query` and `iter_fn`
    to override (e.g. for B3 single-node upsert).
    """
    from bench2.workload import PAIR_QUERY, iter_batches as default_iter

    q = query or PAIR_QUERY
    it = iter_fn or default_iter

    measured_ms: list[float] = []
    success = 0
    errors = 0

    if verbose:
        total_batches = (num_pairs + batch_size - 1) // batch_size
        print(f"[bench:{name}] {num_pairs:,} pairs in {total_batches} batches "
              f"(warmup={warmup_batches}, batch={batch_size})")

    t0_meas = None
    for idx, ops in enumerate(
        it(start_id=start_id, num_pairs=num_pairs, batch_size=batch_size, seed=seed)
        if it is default_iter else
        it(start_id=start_id, num_ops=num_pairs, batch_size=batch_size, seed=seed)
    ):
        is_warmup = idx < warmup_batches
        if not is_warmup and t0_meas is None:
            t0_meas = time.perf_counter()

        t0 = time.perf_counter()
        try:
            client._graph.query(q, params={"ops": ops})
            ok = True
        except Exception as exc:  # pragma: no cover
            ok = False
            if verbose:
                print(f"[bench:{name}] batch {idx} FAILED: {exc}")

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if is_warmup:
            continue
        if ok:
            success += 1
            measured_ms.append(elapsed_ms / len(ops))  # per-op latency
        else:
            errors += 1

        if verbose and (idx + 1) % 50 == 0:
            print(f"[bench:{name}]   batch {idx + 1} avg={sum(measured_ms[-50:]) / max(1, len(measured_ms[-50:])):.3f} ms/op")

    total_s = (time.perf_counter() - t0_meas) if t0_meas else 0.0
    measured_sorted = sorted(measured_ms)
    measured_ops = success * batch_size  # approx; last batch may be < batch_size
    avg = sum(measured_ms) / len(measured_ms) if measured_ms else 0.0

    return RunResult(
        benchmark=name,
        indexed=indexed,
        ops=measured_ops,
        batch_size=batch_size,
        total_s=round(total_s, 4),
        ops_per_sec=round(measured_ops / total_s, 1) if total_s > 0 else 0.0,
        per_op_avg_ms=round(avg, 4),
        per_op_p50_ms=round(_percentile(measured_sorted, 50), 4),
        per_op_p95_ms=round(_percentile(measured_sorted, 95), 4),
        per_op_p99_ms=round(_percentile(measured_sorted, 99), 4),
        per_op_min_ms=round(measured_sorted[0], 4) if measured_sorted else 0.0,
        per_op_max_ms=round(measured_sorted[-1], 4) if measured_sorted else 0.0,
        success_batches=success,
        error_batches=errors,
        warmup_batches=warmup_batches,
    )
