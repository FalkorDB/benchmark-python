# FalkorDB Population Benchmark

A Python benchmark tool that measures **FalkorDB data population performance** across increasing graph sizes, with configurable batch sizes and multiple test variants.

## 🔬 Latest finding — Tests 1–5 from **two** EC2 clients (cloud, FalkorDB v4.18.01)

*Same 50-prop CRM record + composite uuid index. Two `c4.xlarge` clients
firing 25K ops each over disjoint id ranges against the same `c6i.8xlarge`
cloud standalone. Combined throughput (Σ = client A + client B) below.*

| Tier | T1 add | T2 audit | T3 W7 (REMOVE) | T4 W7 (active) | **T5 delete** |
|---:|---:|---:|---:|---:|---:|
| **500K Σ ops/s** | 8,014 | 9,671 | 239 | 247 | **20,012** |
| **1M Σ ops/s**   | 9,703 | 9,142 | 140 | 141 | **14,188** |
| **1.5M Σ ops/s** | 9,899 | 6,310 | 104 | 425* | **12,431** |
| **vs single (1M)** | **1.88×** | **1.94×** | **1.02×** | **1.04×** | **1.16×** |

\* T4 1.5M is anomalously fast vs surrounding cells; treat as outlier pending re-run.

**Headline takeaways:**

- **Cheap workloads (T1, T2, T5) scale near-linearly with client count** — adding a second client roughly doubled throughput at 1M.
- **Heavy `SET n = $props` workloads (T3, T4) DO NOT scale.** Combined throughput equals single-client; per-client latency doubles. **Server CPU is the bottleneck — adding application clients won't help customers running W7-shaped writes.**
- Single-client baselines (T1: 0.135 ms, T3: 7.3 ms, T5: 0.075 ms at 1M) are still the canonical numbers; multi-client just confirms the bottleneck location per workload.

Full results + methodology: [`info/bench2-results-cloud.md`](./info/bench2-results-cloud.md)
Multi-client orchestrator: [`scripts/bench2/run_multi_matrix.sh`](./scripts/bench2/run_multi_matrix.sh)

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
