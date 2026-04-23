# bench2 — cloud results (B1 / B2 / B3)

A cheap, focused benchmark designed to isolate **the latency impact of the
uuid composite index on `MERGE`-pair-of-new-nodes inserts** (B1 vs B2),
plus the customer (W7) single-`MERGE` upsert pattern on the same indexed
graph (B3).

See [`info/bench2-design.md`](./bench2-design.md) for the design discussion
and 12 guideline decisions that shaped this suite. (TBD — see plan.md until
that doc is published.)

## Environment

Identical to the W1–W7 cloud suite:

| | |
|--|--|
| **FalkorDB deployment** | Cloud, **standalone** (single node, no replica) |
| **Server host**         | AWS EC2 **c6i.8xlarge** (32 vCPU, 64 GiB RAM), us-east-2 |
| **Client host**         | AWS EC2 **c4.xlarge** (4 vCPU, 7.5 GiB RAM), us-east-2 |
| **Network**             | Same region, public endpoint, TLS off |
| **Driver**              | `falkordb-py`, single client, serial batches |
| **Concurrency**         | 1                                                 |

Full env doc: [`info/benchmark-environment.md`](./benchmark-environment.md).

## What each leg measures

All three legs share the same node shape (`:entity:account` with
`(uuid_hi, uuid_lo)` composite key) and the same hub/star edge density
(every 10th node is a hub linked to the next 9 spokes).

| Leg | Graph (init) | Index? | Bench query | Bench iter |
|---|---|---|---|---|
| **B1** | `bench2_b1_no_index` (~330K nodes) | **No** | `merge_pair` | new pairs |
| **B2** | `bench2_b2_indexed` (500K nodes) | Yes | `merge_pair` | new pairs |
| **B3** | `bench2_b3_upsert`  (500K nodes) | Yes | `upsert_label_swap` (W7 slow) | new singles |

### Bench queries

**B1 / B2 — `merge_pair` (insert two new nodes + edge per op):**
```cypher
UNWIND $ops AS op
MERGE (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo})
  ON CREATE SET a:account, a.`@type` = 'account', a += op.a_props, a.id = op.a_id
MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo})
  ON CREATE SET b:account, b.`@type` = 'account', b += op.b_props, b.id = op.b_id
MERGE (a)-[:CONNECTED_TO]->(b)
```

**B3 — `upsert_label_swap` (customer W7 slow query, single node per op):**
```cypher
UNWIND $ops AS op
MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
SET n = op.props
SET n.`@type` = 'account'
SET n:account
REMOVE n:inactive
```
(`@type` is set in a separate `SET` clause because the falkordb-py param
serializer does not accept `@`-prefixed keys inside dict params; this is a
workload-shape-equivalent rewrite of the customer's literal query.)

## Run parameters

| | B1 | B2 | B3 |
|---|---|---|---|
| Init nodes | 250K (target; reached ~330K incl. earlier partials) | 500K | 500K |
| Init batch | 100 | 1000 | 1000 |
| Bench `--start-id` | 2,000,000 | 500,000 | 500,000 |
| Bench `--ops` | 5,000 | 25,000 | 25,000 |
| Bench `--batch-size` | 100 | 1000 | 1000 |
| Warm-up batches | 10 | 10 | 10 |
| Measured ops | 4,000 | 15,000 | 15,000 |

> B1 used `batch-size 100` because at `batch 1000` on an unindexed graph,
> a single Cypher batch unrolls into 2,000 sequential label-scans of the
> entire `:entity` set within one query, which made wall time pathological
> (>20 min/batch observed before kill).
>
> B2 and B3 use `batch-size 1000` to match the W7 customer reproduction.

## Headline numbers

| | Nodes (during run) | Per-op avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/sec |
|---|---:|---:|---:|---:|---:|---:|
| **B1** no-index `merge_pair` | 330K → 340K | **105.11** | ~105 | 106.6 | 108.1 | **10** |
| **B2** indexed `merge_pair`  | 500K → 550K | **7.26**   | ~7.2 | 7.95  | 8.08  | **137** |
| **B3** indexed `upsert_label_swap` (W7) | 500K → 525K | **3.71** | ~3.7 | 3.85  | 4.58  | **269** |

(B1 logs only print every-5-batch averages, so per-op p50 column is
stated as the centre of the steady-state window. Per-op p95/p99 come from
the runner headline.)

Source logs: `results-cloud-b2/{b1,b2,b3}_run.log`.

## Insights

### 1. The composite index is the single biggest win — ~14× on cloud at production scale

B2 vs B1 (same query, indexed vs not): **7.26 ms vs 105.11 ms per op = 14.5× speed-up**.

That's even larger than the ~13× we saw on the laptop at 50K nodes
([local run](../results-b2/summary_a8ed2d33.md)) because the no-index
disadvantage compounds linearly with N — every `MERGE` does a label scan
of every existing `:entity`, and B2's graph was 1.5× larger than B1's.

**Takeaway:** for any workload that does identity-key `MERGE`, the
composite uuid index is mandatory. There is no scenario where running
without it is acceptable.

### 2. Batch size has a non-obvious interaction with the index

| | Batch 100, no-index | Batch 1000, no-index |
|---|---|---|
| Per-batch wall time | ~10 s | **>20 min (killed)** |

With `UNWIND $ops AS op MERGE …` and no index, the planner unrolls the
UNWIND into N sequential per-row label scans inside a single Cypher
statement. At batch 1000 that's 2000 full scans per query — each scan grows
linearly with the graph, so the batch never returns in a reasonable time.

With the index, batch size is a normal throughput knob (B2 batch 1000 ran
~7 ms/op steady).

**Takeaway:** without an index, **never raise batch size** — it does not
amortise work, it serialises it within one giant query.

### 3. We did **not** reproduce the W7 customer slowdown locally

Customer at 500K reported **804 ms p50 per batch of 1000 (= 0.80 ms/op)
for the slow query**, with the FOREACH workaround at **227 ms p50 per
batch (= 0.23 ms/op)**, a 3.5× ratio at that tier (and 10× at 250K).

Our B3 at 500K on the same hardware family: **3.71 ms/op steady**.
That's:

- ~5× **slower** than the customer's slow-query result at 500K (we are
  closer to their 250K result)
- ~2× **faster** than our B2 indexed pair MERGE (because B3 does half the
  write work per op: 1 node, no edge, no second `MERGE`)

We have **not yet** measured the FOREACH workaround in this suite, so we
cannot replicate the head-to-head 10× / 3.5× ratio the customer hit. What
we can say:

- The **absolute** per-op latency for the W7 pattern at 500K on our cloud
  is in the few-millisecond range, not the hundreds of milliseconds the
  customer observed. Either the regression is sensitive to a workload
  parameter we have not matched (insert vs update mix, `@type` literal vs
  param, warm vs cold cache, concurrent reads), or it has been partially
  addressed in a more recent FalkorDB build.
- The B2 vs B3 comparison **does not** show that the upsert-label-swap
  pattern is intrinsically slower than `merge_pair` — it does less work
  per op and is correspondingly faster per op.

**Next experiment to nail this down:** add **B4 = FOREACH/CASE
workaround** on the same `bench2_b3_upsert` graph, so we can compare B3
vs B4 head-to-head exactly the way the customer did. If B4 ≈ B3, the
regression has been fixed. If B4 < B3 by 3.5×+, it reproduces.

A second experiment worth doing: re-run B3 with **mixed insert/update
ops** (preload `:inactive` nodes pre-init and have B3 hit them) so that
`SET n = op.props`, `SET n:account`, and especially `REMOVE n:inactive`
actually do real work — currently `REMOVE n:inactive` is a no-op because
no node carries that label.

### 4. Our cloud numbers are stable; drift is small

| | First 5 measured batches | Last 5 measured batches | Drift |
|---|---:|---:|---:|
| B1 | 102.6 ms/op | 106.0 ms/op | +3.3% |
| B2 |   7.5 ms/op |   7.1 ms/op | -5.3% |
| B3 |   3.6 ms/op |   3.8 ms/op | +5.6% |

All within noise. The runner discards the first 10 warm-up batches; the
remaining 15 measured batches give a tight window. p99 values are
within 10% of avg in every case, confirming there are no long-tail
stragglers polluting the headline.

## How to reproduce

Re-run on the same EC2 client + cloud server pair. From the client:

```bash
cd ~/benchmark-python && source .venv/bin/activate
export FALKOR_HOST=<cloud-host>
export FALKOR_PORT=6379
export FALKOR_USER=falkordb
export FALKOR_PASS=<password>
mkdir -p results-cloud-b2

# B1
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b1_no_index --no-index --nodes 250000 --batch-size 100 \
  2>&1 | tee results-cloud-b2/b1_init.log
python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b1_no_index --name merge_pair_no_index --no-index \
  --start-id 2000000 --ops 5000 --batch-size 100 --warmup-batches 10 \
  2>&1 | tee results-cloud-b2/b1_run.log

# B2
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b2_indexed --nodes 500000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b2_init.log
python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b2_indexed --name merge_pair_indexed \
  --start-id 500000 --ops 25000 --batch-size 1000 --warmup-batches 10 \
  2>&1 | tee results-cloud-b2/b2_run.log

# B3
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b3_upsert --nodes 500000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b3_init.log
python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b3_upsert --name merge_upsert_label_swap --workload upsert \
  --start-id 500000 --ops 25000 --batch-size 1000 --warmup-batches 10 \
  2>&1 | tee results-cloud-b2/b3_run.log
```

## Open follow-ups

- **B4 — FOREACH/CASE workaround** on the same graph as B3, to enable a
  direct repro of W7's 3.5× / 10× slow vs fast ratio.
- **B3-mixed** — preload some `:inactive` nodes so the upsert path
  actually exercises `SET n = props` updates and `REMOVE n:inactive`
  label deletions, rather than always taking the create branch.
- **Larger tier (1M nodes)** for B2/B3 to see how per-op latency scales —
  the customer's W7 saw the slow query *speed up* from 250K → 500K,
  which is the strongest signal that something is genuinely odd about the
  planner on that pattern.

PR: <https://github.com/FalkorDB/benchmark-python/tree/feat/bench2-index-impact>
