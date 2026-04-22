# bench2 — index impact (a8ed2d33)

- **Run timestamp (UTC):** 2026-04-22T19:21:31+00:00
- **Workload:** MERGE 2 new `:entity:account` nodes + `[:CONNECTED_TO]` edge
- **Ops per benchmark:** 25,000 attempted (first 10 batches × 100 = 1,000 ops discarded as warm-up)
- **Batch size:** 100 ops

## Side-by-side

| Metric | B1 `merge_pair_no_index` (no index) | B2 `merge_pair_indexed` (indexed) | Δ (B2 vs B1) |
|--------|---:|---:|---:|
| ops/sec | 72.7 | 917.7 | +1162.3% |
| per-op avg (ms) | 13.7014 | 1.0476 | -92.4% |
| per-op p50 (ms) | 13.6630 | 1.0544 | -92.3% |
| per-op p95 (ms) | 17.5720 | 1.2219 | -93.0% |
| per-op p99 (ms) | 19.3327 | 1.2726 | -93.4% |
| per-op min (ms) | 9.0105 | 0.8300 | -90.8% |
| per-op max (ms) | 21.1872 | 1.4092 | -93.3% |
| total_s (measured) | 329.915 | 26.151 | -92.1% |
| success batches | 240 | 240 | — |
| error batches | 0 | 0 | — |

Negative Δ on latency = B2 is faster. Positive Δ on ops/sec = B2 is faster.
