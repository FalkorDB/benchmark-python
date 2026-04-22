# bench2 — run e9b2206f

- **Run timestamp (UTC):** 2026-04-22T20:04:00+00:00
- **Workloads run:** merge_pair_no_index, merge_pair_indexed, merge_upsert_label_swap
- **Ops per benchmark (measured):** 24,000  (first 10 batches × 100 discarded as warm-up)
- **Batch size:** 100 ops

## Side-by-side

| Metric | merge_pair_no_index | merge_pair_indexed | merge_upsert_label_swap |
|--------|---:|---:|---:|
| ops/sec | 74.6 | 897.4 | 1,672.1 |
| per-op avg (ms) | 13.3551 | 1.0540 | 0.5683 |
| per-op p50 (ms) | 13.3345 | 1.0642 | 0.5025 |
| per-op p95 (ms) | 17.2914 | 1.2062 | 0.7617 |
| per-op p99 (ms) | 17.6074 | 1.7290 | 2.0337 |
| per-op min (ms) | 8.8796 | 0.8275 | 0.4154 |
| per-op max (ms) | 18.3757 | 2.4623 | 6.8274 |
| total_s (measured) | 321.836 | 26.745 | 14.353 |
| success batches | 240 | 240 | 240 |
| error batches | 0 | 0 | 0 |

> **Note on direct comparison:** `merge_pair_*` ops touch 2 nodes + 1 edge per op; `merge_upsert_label_swap` touches 1 node + adds/removes labels per op. ops/sec is therefore not directly comparable between pair and upsert workloads. Use per-op latency for like-for-like reasoning, and treat the upsert numbers as a reproduction of the customer (W7) pattern on the same indexed graph.
