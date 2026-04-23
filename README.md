# FalkorDB Population Benchmark

A Python benchmark tool that measures **FalkorDB data population performance** across increasing graph sizes, with configurable batch sizes and multiple test variants.

## 🔬 Latest finding — Test 1 vs Test 2: cost of two audit SETs after a MERGE (cloud, v4.18.01)

*Same 50-prop CRM record, same composite uuid index, single client thread on AWS c4.xlarge → c6i.8xlarge cloud.
**Test 1** = `MERGE (n:entity:account {uuid_hi, uuid_lo}) ON CREATE SET n = $props`.
**Test 2** = Test 1 + `SET n.updated_at = $updated_at` + `SET n.version = coalesce(n.version, 0) + 1`.*

| Tier | T1 ms/op | T2 ms/op | Δ per op | Δ % | T1 ops/s | T2 ops/s |
|---:|---:|---:|---:|---:|---:|---:|
| **500K** | 0.126 | **0.141** | +0.015 | **+12.2%** | 5,422 | 4,998 |
| **1M**   | 0.135 | **0.153** | +0.018 | **+13.6%** | 5,162 | 4,708 |
| **1.5M** | 0.138 | **0.146** | +0.008 | **+5.4%**  | 5,082 | 4,887 |

**Findings:**

- **Two extra SETs cost ~0.015 ms / ~10–13%** per op. Small but measurable; the second SET is intentionally read-then-write (via `coalesce`) so this isn't a no-op write.
- **Both tests scale sublinearly:** 500K→1.5M is +9.4% on Test 1, only +3.5% on Test 2 — extra fixed per-op work dilutes the already-small index-lookup growth.
- **No within-run drift** in any of the 6 runs.
- **Capacity numbers:** ~5,200 add-new-node ops/sec without audit, ~4,900 ops/sec with audit, single client, at 1M+ scale.

Full results, methodology, per-batch drift: [`info/bench2-results-cloud.md`](./info/bench2-results-cloud.md)

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
