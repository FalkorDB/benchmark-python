# FalkorDB Population Benchmark

A Python benchmark tool that measures **FalkorDB data population performance** across increasing graph sizes, with configurable batch sizes and multiple test variants.

## 🚨 Latest finding — noisy-neighbor labels cost 20× at 1M (bench2, cloud)

*Apples-to-apples, FalkorDB v4.18.01 standalone on AWS c6i.8xlarge:*

| Graph | Composition | Total index entries | MERGE-pair avg | Throughput |
|---|---|---:|---:|---:|
| B2 1M (clean) | 1M `:entity:account` | 1.0M | **0.090 ms/op** | **9,317 ops/s** |
| B4 1M (noisy) | 1M `:entity:account` + 500K `:entity:contact` *(same composite `:entity(uuid_hi, uuid_lo)` index)* | 1.5M (+50%) | **1.804 ms/op** | **549 ops/s** |
| **Impact** | | | **20× slower** | **17× drop** |

A **50% increase in index cardinality** via a different child label under the **same composite index** produces a **20× latency hit** on writes — wildly super-linear.

**Immediate recommendation:** do **not** share a composite key index across multiple child labels. Partition it — use `:account(uuid_hi, uuid_lo)`, `:contact(uuid_hi, uuid_lo)`, etc. as separate indexes.

See the full report with methodology, all legs (B1/B2/B3/B4), W7 customer pattern reproduction at 1M, and reproduction commands:
[`info/bench2-results-cloud.md`](./info/bench2-results-cloud.md)

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
