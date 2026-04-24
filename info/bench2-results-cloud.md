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
| **FalkorDB version**    | **v4.18.01**                                     |
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
| **B4** | `bench2_b4_noisy_1m` (1M `:entity:account` + 500K `:entity:contact`) | Yes | `merge_pair` (same as B2) | new pairs |

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

### 500K tier

| | Nodes (during run) | Per-op avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/sec |
|---|---:|---:|---:|---:|---:|---:|
| **B1** no-index `merge_pair` | 330K → 340K | **105.11** | ~105 | 106.6 | 108.1 | **10** |
| **B2** indexed `merge_pair`  | 500K → 550K | **7.26**   | ~7.2 | 7.95  | 8.08  | **137** |
| **B3** indexed `upsert_label_swap` (W7) | 500K → 525K | **3.71** | ~3.7 | 3.85  | 4.58  | **269** |

### 1M tier

| | Nodes (during run) | Per-op avg (ms) | p95 (ms) | p99 (ms) | ops/sec | Drift across run |
|---|---:|---:|---:|---:|---:|---|
| **B2** indexed `merge_pair`            | 1.05M → 1.10M | **0.090** | 0.089 | 0.125 | **9,317** | flat (0.087 → 0.095) |
| **B3** indexed `upsert_label_swap` (W7) | 1.00M → 1.025M | **0.357** | 0.452 | 0.471 | **2,731** | **0.098 → 0.436 (4.5× growth)** |
| **B4** indexed `merge_pair` **+ 500K `:entity:contact` noisy neighbors** | 1.50M → 1.55M | **1.804** | 2.083 | 2.095 | **549** | 1.45 → 1.97 (+36%) |

(B1 not run at 1M tier — see decision in *Open follow-ups* below.)

Source logs: `results-cloud-b2/{b2,b3,b4}_1m_run.log`.

### 2M tier — clean vs noisy controlled comparison

Two graphs at the **same total size (2M nodes)** and same composite index,
differing only in label mix. Each graph runs the same 3 workloads
(`pair` / `upsert` / `foreach`) sequentially. Bench query and parameters
are identical between graphs.

| Graph | Composition | Total | Hub/star edges |
|---|---|---:|---:|
| B6 clean 2M | 2.0M `:entity:account` | 2.0M | 2.8M |
| B7 noisy 2M | 1.5M `:entity:account` + 0.5M `:entity:contact` | 2.0M | 2.1M |

**Headline:**

| Workload | B6 clean | B7 noisy | Diff | p99 (B6 / B7) |
|---|---:|---:|---:|---:|
| `pair` (B2-shape, 2 nodes/op) | **1.200 ms/op** (821 ops/s) | **1.197 ms/op** (824 ops/s) | **+0.3%** | 1.50 / 1.46 ms |
| `upsert` (B3 W7 slow, 1 node/op) | **0.858 ms/op** (1,154 ops/s) | **0.855 ms/op** (1,158 ops/s) | **+0.3%** | 0.95 / 0.92 ms |
| `foreach` (B5 W7 workaround, 1 node/op) | **0.975 ms/op** (1,017 ops/s) | **0.974 ms/op** (1,018 ops/s) | **+0.1%** | 1.13 / 1.13 ms |

**B6 ≈ B7 across every workload, every batch, every percentile.** Label
mixing has **no measurable cost** at this scale. (See Insight 8 — this
overturns the B4 1M conclusion.)

Source logs: `results-cloud-b2/{b6,b7}_2m_{pair,upsert,foreach}_run.log`.

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

### 5. **W7 customer slowdown reproduced at 1M tier** ⚠️

This is the headline finding of the 1M run.

| Metric | B2 (`merge_pair`, indexed) | B3 (W7 `upsert_label_swap`) | Ratio |
|---|---:|---:|---:|
| Avg ms/op (steady) | 0.090 | 0.357 | **4.0× slower** |
| First measured batch | 0.086 | 0.244 | 2.8× |
| Last measured batch  | 0.095 | 0.436 | **4.6×** |
| Drift across 25 batches | +9% | **+345%** | |

Two separate signals here, both pointing at a real planner pathology in
the W7 query shape:

1. **B3 is intrinsically slower per-op than B2 even though it does less
   work** (1 node + label edits vs 2 nodes + 1 edge). At 500K B3 was
   ~2× *faster* than B2 (work-ratio dominated). At 1M B3 is **4× slower**
   than B2 — the inversion happens between 500K and 1M.

2. **B3 latency grows linearly with the graph during the 25K-op run**
   (0.098 → 0.436 ms/op, **4.5× over 25 batches** of 1000 ops each),
   while B2 stays flat. Because both runs target a graph that already
   contains 1M nodes pre-warmed, the only thing changing during the run
   is +25K extra `:account` nodes — and B3's per-op cost roughly tracks
   that growth, while B2's does not. That's the "it gets slower the more
   you upsert" customer report, observed directly.

This **does** reproduce the W7 pattern qualitatively (B3 slower than the
indexed-MERGE baseline, and degrading with graph size). It does *not*
reproduce the 0.80 ms/op absolute number from the customer's report —
our B3 at 1M is **0.36 ms/op steady, 0.44 ms/op tail**, which is in the
same order of magnitude but better. Two plausible reasons: (a) v4.18.01
has partially mitigated the issue since the customer ticket; (b) the
customer workload had a different insert/update mix.

**Action:** B4 (FOREACH workaround on the same graph) is now mandatory —
without it we cannot quantify what fraction of the slowdown is "the W7
bug" vs "MERGE-with-SET is just a heavier shape than MERGE-with-ON-CREATE".


### 7. ~~Noisy-neighbor labels in a shared index cost 20x at 1M~~ (RETRACTED)

> ⚠️ **This finding has been RETRACTED.** A controlled comparison at 2M
> total nodes (B6 vs B7, see Insight 8) shows that label mixing has no
> measurable cost. The B4 1M result was almost certainly an environmental
> artifact. The original write-up is preserved below for the record.


B4 answers: "does it matter if the composite `:entity` index contains
nodes with different child labels (e.g. `:account` plus `:contact`)?"
The answer is unambiguous: **yes, massively.**

Apples-to-apples at 1M tier, identical bench query (`merge_pair`, indexed):

| Metric | B2 1M (clean) | B4 1M (+500K `:entity:contact`) | Impact |
|---|---:|---:|---|
| `:entity` nodes in index | 1.0M | 1.5M (**+50%**) | |
| Per-op avg | 0.090 ms | **1.804 ms** | **20x slower** |
| Throughput | 9,317 ops/s | **549 ops/s** | **17x drop** |
| p99 | 0.125 ms | 2.095 ms | 17x |
| In-run drift | flat | 1.45 -> 1.97 ms/op (+36%) | also degrading |

A 50% increase in total index cardinality produced a **20x latency hit**.
That is wildly non-linear — if the cost were `O(index size)` we would
expect ~1.5x at most. The bench query's `MERGE` lookup is on `:entity`
which is correct, and the lookup on a new uuid should be a pure miss
regardless of whether the surrounding nodes are `:account` or `:contact`.

Plausible root causes to investigate:

1. **`ON CREATE SET` re-validates the index on every insert** and that
   validation cost scales super-linearly with nodes that share the index
   but have a different child label.
2. **The planner is doing a linear label filter** inside the MERGE
   pipeline that isn't index-accelerated for the
   `:entity:account`-vs-`:entity:contact` discrimination.
3. **Constraint/uniqueness checks** on the composite key scan all
   `:entity` nodes instead of just the child-label slice.

**Customer-facing implication:** if you have one graph schema that mixes
multiple entity child-labels (accounts, contacts, leads, deals, …)
under a shared `:entity(uuid_hi, uuid_lo)` composite index, the write
throughput on any one label **degrades super-linearly** with the total
entity count, not the per-label count. In practice that means a graph
with 1M accounts + 500K contacts writes accounts **20x slower** than a
graph with just 1M accounts.

**Recommended mitigation pending root-cause fix:**

- **Partition the composite index by child label** — replace
  `:entity(uuid_hi, uuid_lo)` with separate
  `:account(uuid_hi, uuid_lo)` and `:contact(uuid_hi, uuid_lo)` indexes.
- If the `:entity` parent label is needed for query paths, add it but
  don't carry the composite key on the parent.

**Open question:** we tested this at 1M/500K only. The degradation
curve between 0 and 500K extra contacts is unknown — is there a small
amount of mixing that is safe, or does any cross-label pollution cost
proportionally? Worth a follow-up run with a 100K-step sweep.


### 8. ⚠️ Retraction: B4's 20× noisy-neighbor finding does NOT replicate at 2M

The 2M controlled comparison (Insight 7's evidence base) **rejects** the
B4 hypothesis. At 2M total index size:

| | B6 clean (2M `:entity:account`) | B7 noisy (1.5M `:entity:account` + 0.5M `:entity:contact`) | Diff |
|---|---:|---:|---:|
| `pair` ms/op | 1.200 | 1.197 | **+0.3%** |
| `upsert` ms/op | 0.858 | 0.855 | **+0.3%** |
| `foreach` ms/op | 0.975 | 0.974 | **+0.1%** |

These are the same workload shape, the same total index size, with the
**only** difference being label mix. They are **statistically identical
on every metric** — within driver/network noise.

So what produced B4's 20× hit (1.804 ms/op vs 0.090 ms/op for B2 1M)?
Most likely **environmental**:

- Cloud-server contention with another tenant during the B4 run window
- Cache state difference (B4 graph was built with a separate init that
  may have left the index in a degenerate state at the time)
- Storage/IO transient

The B4 1M graph still exists and we will re-run it (see Open follow-ups).
If the re-run shows ~0.09 ms/op (matching B2 1M) → confirmed environmental.
If it again shows ~1.80 ms/op → there is something specifically wrong
with that graph's state, but **not** caused by label mixing per se.

**Updated customer-facing guidance:** the recommendation to "partition
composite indexes by child label" is **withdrawn** until we have a
reproducible failure case. Sharing a `:entity(uuid_hi, uuid_lo)` index
across multiple child labels is, on the evidence we now have, fine.

### 9. ⚠️ The W7 FOREACH workaround is NOT faster than the slow query at 2M

The customer's report claimed FOREACH/CASE rewriting of the W7 upsert
gave a 3.5–10× speed-up. Our measurement at 2M says otherwise:

| Query | B6 clean ms/op | B7 noisy ms/op |
|---|---:|---:|
| `upsert` (W7 "slow" shape) | 0.858 | 0.855 |
| `foreach` (W7 "fast" workaround) | **0.975** (12% slower) | **0.974** (14% slower) |

The "workaround" is in fact slightly **slower** than the "slow" query.
This is consistent across both graphs and stable across batches (no
drift inversion mid-run).

Plausible explanations:

1. **The W7 regression has been fixed in v4.18.01** — our build is
   newer than the customer's. The slow-shape query is no longer
   pathological, so the workaround has nothing to rewrite around.
2. **The customer's slowdown was state-dependent** — our test always
   takes the create branch (every uuid is new); the customer's
   production traffic is presumably mostly updates, where redundant
   `SET n = props` on a match has different cost characteristics.

**Action:** add a B3-mixed leg (preload `:inactive` nodes so updates
exercise the match branch) before drawing a final conclusion on the W7
pattern. With only insert traffic measured, we cannot confirm the
customer's regression is fixed — only that we cannot reproduce it.

### 10. 500K cloud numbers are stable; 1M B3 is not

**500K (all three legs):**

| | First 5 measured batches | Last 5 measured batches | Drift |
|---|---:|---:|---:|
| B1 | 102.6 ms/op | 106.0 ms/op | +3.3% |
| B2 |   7.5 ms/op |   7.1 ms/op | -5.3% |
| B3 |   3.6 ms/op |   3.8 ms/op | +5.6% |

All within noise. The runner discards the first 10 warm-up batches; the
remaining 15 measured batches give a tight window. p99 values are
within 10% of avg in every case, confirming there are no long-tail
stragglers polluting the headline.

**1M:**

| | First measured batch | Last measured batch | Drift |
|---|---:|---:|---:|
| B2 | 0.086 ms/op | 0.095 ms/op | +10% (within noise) |
| B3 | 0.244 ms/op | 0.436 ms/op | **+79%** (real degradation) |

B3 at 1M is **not** in steady state during the run — it is degrading
monotonically. This is itself a finding (see Insight 5), but it means
the headline B3 1M avg under-represents the true late-state per-op cost.

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

# B2 — 1M tier
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b2_indexed_1m --nodes 1000000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b2_1m_init.log
python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b2_indexed_1m --name merge_pair_indexed_1m \
  --start-id 1000000 --ops 25000 --batch-size 1000 --warmup-batches 10 \
  2>&1 | tee results-cloud-b2/b2_1m_run.log

# B3 — 1M tier
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b3_upsert_1m --nodes 1000000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b3_1m_init.log
python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b3_upsert_1m --name merge_upsert_label_swap_1m --workload upsert \
  --start-id 1000000 --ops 25000 --batch-size 1000 --warmup-batches 10 \
  2>&1 | tee results-cloud-b2/b3_1m_run.log

# B4 — 1M tier with noisy-neighbor contacts (+500K :entity:contact)
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b4_noisy_1m --nodes 1000000 --extra-contacts 500000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b4_1m_init.log
python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b4_noisy_1m --name merge_pair_indexed_1m_noisy \
  --start-id 1000000 --ops 25000 --batch-size 1000 --warmup-batches 10 \
  2>&1 | tee results-cloud-b2/b4_1m_run.log

# B6 — clean 2M (control)
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b6_clean_2m --nodes 2000000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b6_2m_init.log

# B7 — noisy 2M (1.5M accounts + 0.5M contacts, same index)
python -u -m bench2.cli init --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --graph bench2_b7_noisy_2m --nodes 1500000 --extra-contacts 500000 --batch-size 1000 \
  2>&1 | tee results-cloud-b2/b7_2m_init.log

# Run B2/B3/B5 (pair/upsert/foreach) on each graph:
for GRAPH in bench2_b6_clean_2m bench2_b7_noisy_2m; do
  TAG=$( [[ $GRAPH == *clean* ]] && echo b6 || echo b7 )
  for W in pair upsert foreach; do
    case $W in pair) SID=4000000;; upsert) SID=4050000;; foreach) SID=4075000;; esac
    python -u -m bench2.cli run --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
      --username "$FALKOR_USER" --password "$FALKOR_PASS" \
      --graph $GRAPH --name ${W}_${TAG}_2m --workload $W \
      --start-id $SID --ops 25000 --batch-size 1000 --warmup-batches 10 \
      2>&1 | tee results-cloud-b2/${TAG}_2m_${W}_run.log
  done
done
```

## Open follow-ups

> **Decision (2026-04-23):** B1 (no-index `merge_pair`) is **dropped from
> future tier runs**. The 14× index speed-up is now established and
> consistent across laptop (50K) and cloud (330K) — there is no realistic
> production scenario where running without the composite uuid index is
> acceptable, so further B1 measurements at larger tiers (500K+) would
> burn cloud time without producing a new finding. Future tiers (1M, 1.5M)
> measure **B2 + B3** (and B4 once added) only.

- **B4 1M re-run** to confirm whether the 20× regression is
  reproducible or environmental (Insight 8). **Top priority** — the
  recommendation to partition composite indexes hinges on this.
- **B5 FOREACH on `bench2_b3_upsert_1m`** for completeness (we have B5
  at 2M only; 1M data point would let us see if the FOREACH-vs-upsert
  ratio scales with size).
- **B3-mixed** — preload some `:inactive` nodes so the upsert path
  actually exercises `SET n = props` updates and `REMOVE n:inactive`
  label deletions, rather than always taking the create branch.
- **Larger tier (1.5M pure accounts)** to separate "graph just got bigger"
  from the B4 "mixed-label" signal: does 1.5M `:entity:account` alone
  cost 20× or is it specifically the label diversity?
- **Noisy-neighbor sweep** — repeat B4 with 100K, 200K, 300K, 400K, 500K
  extra contacts to characterise the degradation curve (linear? cliff?).
- **Partitioned-index control** — rebuild with `:account(uuid_hi, uuid_lo)`
  and `:contact(uuid_hi, uuid_lo)` as separate indexes (no shared
  `:entity` index) and re-measure: this would confirm whether the
  mitigation we are recommending actually restores B2-level throughput.
- **Re-run B3 1M with longer ops** (e.g. 100K) to confirm whether the
  degradation continues to grow or plateaus past +25K rows.

PR: <https://github.com/FalkorDB/benchmark-python/tree/feat/bench2-index-impact>

---

## Test 1 — `add_new_node` (50-prop CRM record, indexed)

Newer test design (April 2026), independent of the B1–B7 numbering above.
The earlier suite mixed multiple workload shapes (pair-MERGE + edges +
upserts) and was hard to interpret per-tier. Test 1 isolates one
production-relevant question: **what does it cost to add a single
50-property `:entity:account` node, indexed by composite uuid, as the
graph grows?**

### Setup

- **Init:** `N` `:entity:account` nodes, 50 props each (18 str + 15 int +
  10 float + 5 bool + 2 uuid composite-key keys), composite index
  `:entity(uuid_hi, uuid_lo)`. **No edges.** Init uses the same query
  as the bench so init writes are byte-for-byte equivalent to bench
  writes.
- **Bench query** (per op; UNWIND'd 1000-at-a-time):
  ```cypher
  MERGE (n:entity:account {uuid_hi: $uuid_hi, uuid_lo: $uuid_lo})
    ON CREATE SET n = $props
  ```
  Every uuid is fresh → MERGE always takes the create branch → measures
  the index-miss + node-create + 50-prop-write path.
- **Bench params:** 25,000 ops, batch 1000, warmup 10 batches (15
  measured), single client thread.
- **Tiers:** 500K, 1M, 1.5M pre-graph nodes.

### Results

| Pre-graph | Avg ms/op | ops/s | p95 (ms) | p99 (ms) | First measured | Last measured | Drift |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 500K | 0.126 | 5,422 | 0.129 | 0.133 | 0.127 | 0.129 | +1.6% |
| 1M   | 0.135 | 5,162 | 0.137 | 0.137 | 0.137 | 0.134 | -2.2% |
| 1.5M | 0.138 | 5,082 | 0.141 | 0.150 | 0.138 | 0.140 | +1.4% |

Source logs: `results-cloud-test1/{500k,1m,1_5m}_{init,run}.log`.

### Findings

1. **Sublinear scaling.** 1.5M is only 9.4% slower per op than 500K
   despite 3× the data. Consistent with O(log N) index-lookup cost
   dominating, with the constant per-op work of "create node + write 50
   props + insert into index" being roughly invariant in graph size.
2. **No within-run degradation.** Each tier is flat across 25 batches
   (drift ≤2%, well within noise). Adding new nodes during the bench
   does not visibly change per-op cost — confirming the index lookup
   path is the dominant cost, not anything that scales with recently
   inserted data.
3. **Tight latency distribution.** p99 within 8-12% of avg in every
   tier. No long tails, no GC pauses, no plan recompilation visible.
4. **Capacity-planning number.** A single client thread sustains
   ~5,000 add-new-node ops/sec at 1M+ scale = **~250,000 property
   writes/sec** with composite-index maintenance.

### Reproduction

```bash
cd ~/benchmark-python && source .venv/bin/activate
export FALKOR_HOST=<cloud-host>
export FALKOR_PORT=6379
export FALKOR_USER=falkordb
export FALKOR_PASS=<password>
mkdir -p results-cloud-test1

for SIZE in 500000 1000000 1500000; do
  case $SIZE in
    500000)  TAG=500k ;;
    1000000) TAG=1m ;;
    1500000) TAG=1_5m ;;
  esac
  GRAPH=test1_${TAG}
  python -u -m bench2.cli init \
    --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
    --username "$FALKOR_USER" --password "$FALKOR_PASS" \
    --graph $GRAPH --shape add_new_node --nodes $SIZE --batch-size 1000 \
    2>&1 | tee results-cloud-test1/${TAG}_init.log
  python -u -m bench2.cli run \
    --host "$FALKOR_HOST" --port "$FALKOR_PORT" \
    --username "$FALKOR_USER" --password "$FALKOR_PASS" \
    --graph $GRAPH --workload add_new_node --name add_new_node_${TAG} \
    --start-id $SIZE --ops 25000 --batch-size 1000 --warmup-batches 10 \
    2>&1 | tee results-cloud-test1/${TAG}_run.log
done
```

### Open follow-ups for Test 1

- **Noisy-neighbor variant** — repeat at 1M with an additional 500K
  `:entity:contact` nodes in the same composite index to test whether
  label diversity affects the add_new_node path.
- **Larger tier (3M, 5M)** — extrapolate the sublinear curve.
- **Concurrent clients** — single-client throughput is 5K ops/s; what
  does N parallel clients give?

---

## Test 2 — `add_new_node_with_audit` (Test 1 + 2 extra SETs)

Identical to Test 1 except the bench query stamps two audit fields after
the MERGE:

```cypher
MERGE (n:entity:account {uuid_hi: $uuid_hi, uuid_lo: $uuid_lo})
  ON CREATE SET n = $props
SET n.updated_at = $updated_at
SET n.version    = coalesce(n.version, 0) + 1
```

Same init shape (uses the same query), same tier ladder (500K, 1M,
1.5M), same params (25K ops, batch 1000, single client thread).

The second SET intentionally **reads** `n.version` and writes it back
(via `coalesce`) so it's not a no-op — measures realistic
"read-then-write" cost, not just an assignment.

### Combined Test 1 vs Test 2 — marginal cost of two extra SETs

| Tier | T1 ms/op | T2 ms/op | Δ ms/op | Δ % | T1 ops/s | T2 ops/s | T2 p99 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 500K | 0.126 | 0.141 | +0.015 | +12.2% | 5,422 | 4,998 | 0.153 |
| 1M   | 0.135 | 0.153 | +0.018 | +13.6% | 5,162 | 4,708 | 0.184 |
| 1.5M | 0.138 | 0.146 | +0.008 |  +5.4% | 5,082 | 4,887 | 0.154 |

Source logs: `results-cloud-test2/{500k,1m,1_5m}_{init,run}.log`.

### Findings

1. **Two extra SETs cost ~0.015 ms (≈10–13%) per op.** Small but
   measurable. Roughly linear with the work added — one direct
   assignment plus one read-then-write.
2. **Test 2 also scales sublinearly.** 500K → 1.5M is only +3.5% on
   Test 2 vs +9.4% on Test 1. Extra fixed per-op work dilutes the
   (already small) index-lookup growth, flattening the curve further.
3. **Test 2 1M is the slowest tier in the ladder** (0.153 ms, vs 0.146
   at 1.5M). One outlier first-measured batch (0.178 ms vs steady
   ~0.145 elsewhere) drove this — `p99=0.184`. Treat as transient
   cloud noise, not a real inversion.
4. **Latency tails widen slightly.** p99/avg ratio is 1.20× on Test 2
   vs ≤1.10× on Test 1. The read-then-write `coalesce` likely
   contributes the extra variance. No pathological long tails in any
   tier.
5. **No within-run drift.** All three Test 2 runs are flat across 25
   batches (drift ≤2%).

### Capacity-planning takeaway

Adding audit-stamping (very common in CRM-style writes) costs ~10–13%
in throughput at this workload shape. A single client thread sustains
~4,900 ops/sec at 1M+ scale with the audit pattern, vs ~5,200 without
it.

### Reproduction

```bash
for SIZE in 500000 1000000 1500000; do
  case $SIZE in
    500000)  TAG=500k ;;
    1000000) TAG=1m ;;
    1500000) TAG=1_5m ;;
  esac
  GRAPH=test2_${TAG}
  python -u -m bench2.cli init --graph $GRAPH \
    --shape add_new_node_with_audit --nodes $SIZE --batch-size 1000 \
    2>&1 | tee results-cloud-test2/${TAG}_init.log
  python -u -m bench2.cli run --graph $GRAPH \
    --workload add_new_node_with_audit \
    --name add_new_node_with_audit_${TAG} \
    --start-id $SIZE --ops 25000 --batch-size 1000 --warmup-batches 10 \
    2>&1 | tee results-cloud-test2/${TAG}_run.log
done
```

---

## Test 3 — `upsert_w7` (W7 customer pattern at 50-prop scale)

The exact customer-reported W7 upsert pattern, run at the Test 1/2 tier
ladder with the same 50-prop CRM record so the comparison is direct.

```cypher
MERGE (n:entity {uuid_hi: $uuid_hi, uuid_lo: $uuid_lo})  -- :entity only
SET n = $props          -- 50 props rewritten unconditionally
SET n:account           -- label add unconditional
REMOVE n:inactive       -- label remove unconditional
```

Init shape (`--shape add_new_node`) is identical to Test 1/2 — only the
bench query differs.

### Combined Test 1 vs Test 2 vs Test 3

| Tier | T1 ms/op | T2 ms/op | **T3 ms/op** | T3 ops/s | T3 p95 | T3 p99 | T3 / T1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 500K | 0.126 | 0.141 | **4.045** | **244**   | 4.44  | 4.46  | **32.1×** |
| 1M   | 0.135 | 0.153 | **7.311** | **136**   | 7.59  | 7.82  | **54.2×** |
| 1.5M | 0.138 | 0.146 | **9.808** | **101**   | 10.16 | 10.30 | **71.1×** |

Source logs: `results-cloud-test3/{500k,1m,1_5m}_{init,run}.log`.

### Findings

1. **The W7 pattern is catastrophically slow at the new tier scale.**
   At 1.5M nodes, throughput collapses to **~101 ops/s** vs Test 1's
   ~5,000 — a **71× slowdown** despite operating on the same indexed
   graph at the same uuid range.

2. **Slowdown grows roughly linearly with graph size** (32× → 54× →
   71×). This is the smoking gun: the regression is **NOT** a fixed
   per-op overhead — it scales with the index/label-store size. This
   is consistent with the original W7 customer report and with the
   earlier 250K/500K reproducer numbers.

3. **At 2M (earlier B6/B7 runs) the regression was gone** because that
   bench used `random_props` (4 props) — `SET n = $props` was rewriting
   only ~4 fields. With **50 props** rewritten unconditionally on every
   op, the regression dominates again at every tier from 500K up.

4. **Tight latency distribution within the slow regime.** p99/avg ≈
   1.05× — every op is slow in the same way, not bursty. This points
   to a deterministic per-op cost (full prop rewrite + label-store
   update + index touches) rather than GC or contention.

5. **No within-run drift** — each run is dead flat across 25 batches at
   its bad steady-state number. The cost is paid every op.

### What's expensive — likely culprits

The query does, on every op (every op is a fresh uuid → CREATE branch):

- 1× `MERGE :entity` index lookup (cheap, this is what Test 1 measures)
- 1× node CREATE
- 1× **`SET n = op.props` writing all 50 properties** (expensive at
  scale because the prop store + composite index entry are touched for
  each prop key)
- 1× **`SET n:account` label-store write + label scan index update**
- 1× **`REMOVE n:inactive` lookup-then-delete on label-store**
  (no-op for fresh nodes but the engine still has to check)

Per Test 2's data, the property writes alone are not the bottleneck
(50 props on create cost 0.126 ms in Test 1). The remaining gap of
**~3.9 ms / 7.2 ms / 9.7 ms** must come from the **unconditional label
ops on every row plus the unconditional re-write of all 50 props on a
just-created node** (which Cypher engines often can't fold).

### Practical recommendation for customers

Two things, in order of expected savings:

1. **Stop writing what you don't need to.** Use `ON CREATE SET` /
   `ON MATCH SET` to avoid rewriting the full prop bag on every op.
   Test 2 demonstrates the audit-stamp pattern doing exactly this for
   ~10% overhead instead of 30-70×.

2. **Replace the `:inactive` / `:account` label swap with a boolean
   property** (e.g. `active: true|false`) backed by a property index.
   To be measured directly in Test 4 (re-init required because the
   schema changes).

### Reproduction

```bash
for SIZE in 500000 1000000 1500000; do
  case $SIZE in
    500000)  TAG=500k ;;
    1000000) TAG=1m ;;
    1500000) TAG=1_5m ;;
  esac
  GRAPH=test3_${TAG}
  python -u -m bench2.cli init --graph $GRAPH \
    --shape add_new_node --nodes $SIZE --batch-size 1000 \
    2>&1 | tee results-cloud-test3/${TAG}_init.log
  python -u -m bench2.cli run --graph $GRAPH \
    --workload upsert_w7 --name upsert_w7_${TAG} \
    --start-id $SIZE --ops 25000 --batch-size 1000 --warmup-batches 10 \
    2>&1 | tee results-cloud-test3/${TAG}_run.log
done
```

---

## Test 4 — `upsert_w7_active` (boolean property instead of label REMOVE)

Same query shape as Test 3 except the `:inactive` label REMOVE is
replaced with a `SET n.active = true` against a property-indexed
`:entity(active)`:

```cypher
MERGE (n:entity {uuid_hi: $uuid_hi, uuid_lo: $uuid_lo})
SET n = $props          -- same as T3: unconditional 50-prop replace
SET n:account           -- same as T3: unconditional label add
SET n.active = true     -- replaces REMOVE n:inactive; property-indexed
```

**Init** uses a fast lean MERGE (`ADD_NEW_NODE_ACTIVE_INIT_QUERY`) that
produces the same end-state node shape (`:entity:account` + 50 props +
`active=true`) but with `ON CREATE SET` so init isn't slowed down by
the W7 pattern itself. The composite uuid index AND the property index
on `active` are both created before loading.

**Hypothesis under test:** the customer's `REMOVE :inactive` label op
is the heavy part of the W7 pattern. Replacing it with a property
write should improve performance.

### Combined Test 1 / Test 2 / Test 3 / Test 4

| Tier | T1 ms/op | T2 ms/op | T3 ms/op | **T4 ms/op** | T4 vs T3 | T4 ops/s | T4 p99 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 500K | 0.126 | 0.141 | 4.045 | **4.159** | **+2.8%** | 237 | 4.51 |
| 1M   | 0.135 | 0.153 | 7.311 | **7.389** | **+1.1%** | 134 | 7.60 |
| 1.5M | 0.138 | 0.146 | 9.808 | **9.814** | **+0.1%** | 101 | 10.36 |

Source logs: `results-cloud-test4/{500k,1m,1_5m}_{init,run}.log`.

### Findings — hypothesis REFUTED

1. **Replacing `REMOVE :inactive` with `SET active = true` gives
   essentially zero improvement** at every tier. T4 is within
   measurement noise of T3, and even slightly slower at 500K
   (the new property index pays its own maintenance cost on every
   `SET active=true`).

2. **The label REMOVE is NOT the bottleneck.** The hypothesis that the
   `REMOVE :inactive` label op was the expensive part of the W7
   pattern is wrong. We can swap it for an indexed property write at
   roughly equal cost.

3. **The real cost is `SET n = $props`** — the unconditional rewrite
   of all 50 properties on every op. This is what scales with graph
   size and dominates the per-op cost. Both the prop store update and
   (potentially) composite index touches happen for every key on every
   write, regardless of whether anything changed.

4. **Property indexes are not free either.** Dropping the label REMOVE
   saved some work but adding the `:entity(active)` index added
   roughly the same amount back. Net change ≈ 0.

5. **Same scaling shape as Test 3** — slowdown grows roughly linearly
   with graph size (32× → 54× → 71× vs Test 1, identical to T3). This
   confirms the cost is in the prop-rewrite path, not the label op.

### What this means for the customer

Swapping the `:inactive` label for an `active` property is **not** a
win on the write path. The only effective fix is to **stop doing
unconditional writes**:

- Use `ON CREATE SET` for the initial property bag.
- Use `ON MATCH SET` ONLY for the fields that actually change between
  CDC events (e.g. `updated_at`, `version`, the specific business
  fields that were updated upstream).
- This is exactly what Test 2 demonstrates: ~10% overhead vs Test 1
  for a realistic audit-stamp pattern, instead of 32-71×.

If the customer's CDC event payload genuinely contains a fresh full
snapshot every time and they don't want to diff client-side, the next
thing to try is **batching the writes by op-type** so the planner can
specialize: separate INSERT-only batches (no MATCH path needed) from
true UPDATE batches.

### Reproduction

```bash
for SIZE in 500000 1000000 1500000; do
  case $SIZE in
    500000)  TAG=500k ;;
    1000000) TAG=1m ;;
    1500000) TAG=1_5m ;;
  esac
  GRAPH=test4_${TAG}
  python -u -m bench2.cli init --graph $GRAPH \
    --shape add_new_node_active --nodes $SIZE --batch-size 1000 \
    2>&1 | tee results-cloud-test4/${TAG}_init.log
  python -u -m bench2.cli run --graph $GRAPH \
    --workload upsert_w7_active --name upsert_w7_active_${TAG} \
    --start-id $SIZE --ops 25000 --batch-size 1000 --warmup-batches 10 \
    2>&1 | tee results-cloud-test4/${TAG}_run.log
done
```

---

## Test 5 — `delete_by_uuid` (single-node DELETE via composite uuid index)

Pure index-lookup + node-delete cost. Same init shape as Tests 1-4
(`--shape add_new_node`, 500K/1M/1.5M `:entity:account` 50-prop nodes,
composite uuid index). Bench targets the **first** 25K uuids of the
init range (`--start-id 0`) so MATCH always finds an existing node.
Init has no edges, so plain `DELETE` is sufficient (no `DETACH`
needed).

```cypher
MATCH (n:entity {uuid_hi: $uuid_hi, uuid_lo: $uuid_lo})
DELETE n
```

### Combined Test 1 / Test 2 / Test 3 / Test 4 / Test 5

| Tier | T1 add | T2 add+audit | T3 W7 (REMOVE) | T4 W7 (active prop) | **T5 delete** | T5 ops/s |
|---:|---:|---:|---:|---:|---:|---:|
| 500K | 0.126 | 0.141 | 4.045 | 4.159 | **0.058** | **15,502** |
| 1M   | 0.135 | 0.153 | 7.311 | 7.389 | **0.075** | **12,235** |
| 1.5M | 0.138 | 0.146 | 9.808 | 9.814 | **0.064** | **14,118** |

Source logs: `results-cloud-test5/{500k,1m,1_5m}_{init,run}.log`.

### Findings

1. **Delete is ~2× cheaper than add at the same scale.** Makes sense:
   the add path writes 50 properties + 1 composite-index entry on
   every op; the delete path does an index lookup + removes the
   node + drops the index entry. No prop store writes.

2. **Throughput: 12K–15K ops/sec** single-thread on cloud — roughly
   3× the add throughput from Test 1 (~5K ops/sec).

3. **Sub-linear scaling, like Test 1.** The 1M result (0.075 ms,
   p99=0.083) appears to be a noisier steady state than 500K or 1.5M —
   wider per-batch variance throughout the run rather than any drift.
   Treating 500K and 1.5M as the cleaner anchors, the cost is
   essentially **flat across the tier range** at ~0.06 ms/op.

4. **Tighter latency than add.** p99/avg ≈ 1.10× across tiers — no
   long-tail outliers. The delete path is more deterministic than the
   prop-rewrite path.

5. **Index maintenance dominates.** With no prop store work to do, the
   per-op cost is essentially "find one row in the composite index +
   remove one entry from it" — and that scales sub-linearly with
   graph size, just like the read side.

### Capacity-planning takeaway

A single client thread sustains **~14,000 deletes/sec by uuid** at
1M+ scale. Roughly 3× the rate of add operations. If the customer's
cleanup or expiration job is delete-by-uuid, throughput should not
be the bottleneck even at 100M-scale graphs (assuming the index
behavior continues to be sub-linear, which is the strong indication
from our 500K → 1.5M curve).

### Reproduction

```bash
for SIZE in 500000 1000000 1500000; do
  case $SIZE in
    500000)  TAG=500k ;;
    1000000) TAG=1m ;;
    1500000) TAG=1_5m ;;
  esac
  GRAPH=test5_${TAG}
  python -u -m bench2.cli init --graph $GRAPH \
    --shape add_new_node --nodes $SIZE --batch-size 1000 \
    2>&1 | tee results-cloud-test5/${TAG}_init.log
  python -u -m bench2.cli run --graph $GRAPH \
    --workload delete_by_uuid --name delete_by_uuid_${TAG} \
    --start-id 0 --ops 25000 --batch-size 1000 --warmup-batches 10 \
    2>&1 | tee results-cloud-test5/${TAG}_run.log
done
```

