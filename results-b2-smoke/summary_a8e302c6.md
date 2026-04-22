# bench2 — run a8e302c6

- **Run timestamp (UTC):** 2026-04-22T19:49:14+00:00
- **Workloads run:** merge_pair_no_index, merge_pair_indexed, merge_upsert_label_swap
- **Ops per benchmark (measured):** 300  (first 2 batches × 100 discarded as warm-up)
- **Batch size:** 100 ops

## Side-by-side

| Metric | merge_pair_no_index | merge_pair_indexed | merge_upsert_label_swap |
|--------|---:|---:|---:|
| ops/sec | 1,784.0 | 7,874.3 | 16,318.9 |
| per-op avg (ms) | 0.5283 | 0.1057 | 0.0506 |
| per-op p50 (ms) | 0.5300 | 0.1057 | 0.0503 |
| per-op p95 (ms) | 0.5835 | 0.1058 | 0.0514 |
| per-op p99 (ms) | 0.5835 | 0.1058 | 0.0514 |
| per-op min (ms) | 0.4713 | 0.1057 | 0.0500 |
| per-op max (ms) | 0.5835 | 0.1058 | 0.0514 |
| total_s (measured) | 0.168 | 0.038 | 0.018 |
| success batches | 3 | 3 | 3 |
| error batches | 0 | 0 | 0 |

> **Note on direct comparison:** `merge_pair_*` ops touch 2 nodes + 1 edge per op; `merge_upsert_label_swap` touches 1 node + adds/removes labels per op. ops/sec is therefore not directly comparable between pair and upsert workloads. Use per-op latency for like-for-like reasoning, and treat the upsert numbers as a reproduction of the customer (W7) pattern on the same indexed graph.
