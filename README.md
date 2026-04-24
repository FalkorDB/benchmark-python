# FalkorDB Population Benchmark

A Python benchmark tool that measures **FalkorDB data population performance** across increasing graph sizes, with configurable batch sizes and multiple test variants.

## 🔬 Latest finding — Tests 1–5 cloud write-path map (cloud, FalkorDB v4.18.01)

*Same 50-prop CRM record, same composite uuid index, same 500K/1M/1.5M ladder, single client thread.*

| Tier | T1 add | T2 add+audit | T3 W7 (REMOVE :inactive) | T4 W7 (SET active=true) | **T5 delete** |
|---:|---:|---:|---:|---:|---:|
| **500K** | 0.126 | 0.141 | 4.045 | 4.159 | **0.058** |
| **1M**   | 0.135 | 0.153 | 7.311 | 7.389 | **0.075** |
| **1.5M** | 0.138 | 0.146 | 9.808 | 9.814 | **0.064** |
| ops/s @ 1M | 5,162 | 4,708 | 136 | 134 | **12,235** |

**Headline takeaways:**

- **Delete by uuid is the fastest write op** — ~2× cheaper than add (no prop store writes), throughput ~12–15K ops/sec single-thread.
- **Add (Test 1)** is a flat ~0.13 ms/op — sublinear scaling, ~5K ops/sec at 1M+.
- **Audit-stamping (Test 2)** adds ~10% on top of add — cheap.
- **Customer W7 pattern (Test 3)** collapses by 32–71× and **scales linearly with graph size**, because it rewrites all 50 props unconditionally on every op.
- **Replacing `:inactive` label with `active` property (Test 4)** does NOT help — refutes the "label REMOVE is the heavy part" hypothesis. The unconditional `SET n = $props` is the actual cost driver.
- **Recommendation:** for upserts, use `ON CREATE SET` / `ON MATCH SET` and write only what changed. Test 2 demonstrates this works at ~10% overhead vs 32–71× for unconditional rewrites.

Full results, methodology, per-batch drift, all 5 tests: [`info/bench2-results-cloud.md`](./info/bench2-results-cloud.md)

---

## Two benchmark suites in this repo

- **`benchmark/`** — throughput sweep across node/edge/index variants at 10K → 1M scale. Documented below.
- **`bench2/`** — focused latency studies on specific workload shapes (MERGE-pair, W7 upsert, noisy-neighbor labels). Reproduces real customer reports. See [`info/bench2-results-cloud.md`](./info/bench2-results-cloud.md).

## Test Types

| Test | Nodes | UUID | UUID Index | Edges | Description |
|------|-------|------|------------|-------|-------------|
| `baseline` | ✅ 100 props | ❌ | ❌ | ❌ | Pure node creation |
| `uuid` | ✅ 100 props | ✅ | ❌ | ❌ | Node creation with UUID property |
| `uuid_indexed` | ✅ 100 props | ✅ | ✅ | ❌ | UUID + index maintenance cost |
| `uuid_edges` | ✅ 100 props | ✅ | ❌ | ✅ 10/5 nodes | UUID + edge creation overhead |
| `uuid_indexed_edges` | ✅ 100 props | ✅ | ✅ | ✅ 10/5 nodes | Full: UUID + index + edges |

**Edge logic:** every 5 consecutive nodes are connected with 10 edges (all pairs).

## Growth Tiers (default)

| Tier | Nodes | Properties/Node |
|------|------:|:---------------:|
| 1 | 10,000 | 100 |
| 2 | 50,000 | 100 |
| 3 | 100,000 | 100 |
| 4 | 500,000 | 100 |
| 5 | 1,000,000 | 100 |

## Quick Start

```bash
# Start FalkorDB
docker run --rm -p 6379:6379 falkordb/falkordb

# Install
pip install -e .

# Run all 5 test types across all tiers (default)
benchmark populate

# Run with a custom batch size
benchmark populate --batch-size 1000

# Run only specific tiers
benchmark populate --tiers 10000 --tiers 100000

# Run only specific test types
benchmark populate --tests baseline --tests uuid_edges

# Custom host/port and graph name
benchmark populate --host localhost --port 6379 --graph my_benchmark

# Disable file output
benchmark populate --no-save --no-csv
```

## CLI Options

```
--host TEXT           FalkorDB host                          [default: localhost]
--port INTEGER        FalkorDB port                          [default: 6379]
--graph TEXT          Graph name                             [default: benchmark]
--tiers INTEGER       Node counts per tier (repeatable)      [default: 10K–1M]
--batch-size INTEGER  Nodes per UNWIND batch                 [default: 500]
--label TEXT          Node label                             [default: Entity]
--tests CHOICE        Test types to run (repeatable)         [default: all five]
--save / --no-save    Save JSON results                      [default: save]
--csv / --no-csv      Save CSV results                       [default: csv]
```

## Output

Results are printed as a **rich terminal table**:

```
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┓
┃ Test Type          ┃ Tier (nodes) ┃ Batch Size ┃ Total Time ┃ Nodes/sec ┃ Avg Batch (ms) ┃ Batches ┃ Errors ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━┩
│ baseline           │    1,000,000 │        500 │    196.42s │     5,091 │           62.3 │    2000 │      0 │
│ uuid_indexed_edges │    1,000,000 │        500 │    346.32s │     2,888 │          130.8 │    2000 │      0 │
└━━━━━━━━━━━━━━━━━━━━┴━━━━━━━━━━━━━━┴━━━━━━━━━━━━┴━━━━━━━━━━━━┴━━━━━━━━━━━┴━━━━━━━━━━━━━━━━┴━━━━━━━━━┴━━━━━━━━┘
```

Results are also saved to `results/` as **JSON** and **CSV**.

## Sample Results

Throughput (nodes/sec) on a local Docker FalkorDB instance:

| Test Type | 10K | 50K | 100K | 500K | 1M |
|---|---|---|---|---|---|
| baseline | 4,338 | 5,279 | 5,735 | 5,172 | 5,091 |
| uuid | 5,445 | 5,635 | 5,364 | 5,332 | 4,833 |
| uuid_indexed | 5,305 | 5,772 | 5,186 | 5,002 | 4,803 |
| uuid_edges | 3,475 | 3,576 | 3,277 | 3,196 | 3,057 |
| uuid_indexed_edges | 3,414 | 3,543 | 3,098 | 3,143 | 2,888 |

## Architecture

```
benchmark/
├── cli.py              ← Click CLI entry point
├── data_gen.py          ← Node/edge data generation, UNWIND query builder
├── falkor_client.py     ← FalkorDB client wrapper with timing
├── metrics.py           ← Per-batch metrics collection
└── reporter.py          ← Rich table + JSON/CSV export
```

Each node has **100 properties**: 40 strings, 30 integers, 20 floats, 10 booleans.
Nodes are inserted in batches using `UNWIND $nodes AS node CREATE ...`.
Edges use `UNWIND $edges AS edge MATCH ... CREATE (a)-[:CONNECTED_TO]->(b)`.

## License

MIT
