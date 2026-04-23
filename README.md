# FalkorDB Population Benchmark

A Python benchmark tool that measures **FalkorDB data population performance** across increasing graph sizes, with configurable batch sizes and multiple test variants.

## 🔬 Latest finding — W7 customer pattern is 32×–71× slower than `add_new_node` and **scales with graph size** (cloud, v4.18.01)

*Same 50-prop CRM record, same composite uuid index, same 500K/1M/1.5M ladder, single client thread.
**Test 1** = lean MERGE (`MERGE :entity:account` + `ON CREATE SET n = $props`).
**Test 2** = T1 + 2 audit SETs.
**Test 3** = customer W7 pattern (`MERGE :entity` + unconditional `SET n=$props` + `SET :account` + `REMOVE :inactive`).*

| Tier | T1 ms/op | T2 ms/op | **T3 ms/op** | T3 ops/s | **T3 / T1** |
|---:|---:|---:|---:|---:|---:|
| **500K** | 0.126 | 0.141 | **4.045** | 244   | **32.1×** |
| **1M**   | 0.135 | 0.153 | **7.311** | 136   | **54.2×** |
| **1.5M** | 0.138 | 0.146 | **9.808** | 101   | **71.1×** |

**Findings:**

- **The W7 upsert pattern collapses at scale.** At 1.5M nodes the same indexed graph drops from ~5,000 ops/sec (T1) to ~101 ops/sec (T3) on identical hardware.
- **The regression scales linearly with graph size** (32× → 54× → 71×). This is the smoking gun — it's not a fixed per-op overhead, it's growing with the label/index store. Consistent with the original customer report and the earlier 250K/500K W7 reproducer.
- **Earlier 2M re-runs saw NO regression** because they used a 4-prop record. With **50 props rewritten unconditionally on every op**, the regression dominates again.
- p99/avg ≈ 1.05× — every op is slow in the same way, not bursty.

**Customer guidance:** stop unconditional rewrites (`ON CREATE SET` + `ON MATCH SET` for only what changed — see Test 2 for the audit pattern at ~10% overhead). Test 4 (next) will measure replacing the `:inactive` label swap with an `active: bool` indexed property.

Full results, per-batch drift, hypothesised cost breakdown: [`info/bench2-results-cloud.md`](./info/bench2-results-cloud.md)

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
