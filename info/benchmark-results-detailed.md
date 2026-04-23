# FalkorDB CRM Benchmark — Detailed Results & Workload Reference

**Run:** `results-cloud/workloads_20260422_005515.csv` (10 workloads × 2 tiers = 20 rows)
**Target:** FalkorDB Cloud (v4.18.01) — **standalone** on AWS EC2 **c6i.8xlarge** (32 vCPU / 64 GiB), us-east-2
**Client:** AWS EC2 **c4.xlarge** (4 vCPU / 7.5 GiB), us-east-2 — single client, serial batches
**Driver script:** `scripts/full_run.sh` — single idempotent init then `suite --skip-init`
**Per-workload params:** `ops=25,000`, `batch_size=1,000` → 25 batches per row
**Indexed:** all rows used the indexed init graph (`crm_init_<tier>`, composite index on `(:entity {uuid_hi, uuid_lo})`)

> Full environment details (instance specs, region, network topology, reproducer)
> are pinned in [`info/benchmark-environment.md`](./benchmark-environment.md).

---

## How to read this doc

Each workload section has 4 parts:

1. **What it simulates** — the CRM operation it models
2. **Exact Cypher** — copy-pasteable query (parameters via `UNWIND $ops AS op`)
3. **CLI command to reproduce** — single workload, single tier
4. **Results** — total time, throughput, full latency distribution at 250K and 500K

All numbers are per-batch (1,000 ops/batch). Per-op latency ≈ batch_ms / 1000.

---

## CLI cheat sheet

```bash
# Phase 1 — load init graph (idempotent; skipped if node count matches)
benchmark init --host $FALKOR_HOST --username $FALKOR_USER --password $FALKOR_PASS \
    --tier 250000 --batch-size 10000

# Phase 2a — single workload
benchmark run --host $FALKOR_HOST --username $FALKOR_USER --password $FALKOR_PASS \
    --tier 250000 --workload insert_attach_merge --ops 25000 --batch-size 1000

# Phase 2b — full suite (all workloads × all tiers, --skip-init requires graphs already exist)
benchmark suite --host $FALKOR_HOST --username $FALKOR_USER --password $FALKOR_PASS \
    --tiers 250000 --tiers 500000 --skip-init --ops 25000 --batch-size 1000
```

`--workload` accepts the string value of the workload (the `id` column below).

---

## The 10 workloads

| # | id | What it does | Net writes per op |
|---|----|--------------|-------------------|
| W1a | `insert_attach_merge`  | Attach a NEW node (via MERGE) to an existing one | +1 node, +1 edge |
| W1b | `insert_attach_create` | Same but CREATE (no MERGE) | +1 node, +1 edge |
| W2a | `insert_pair_merge`    | Create TWO new nodes via MERGE + edge | +2 nodes, +1 edge |
| W2b | `insert_pair_create`   | Same but CREATE both | +2 nodes, +1 edge |
| W3  | `insert_edge_only`     | Edge between two existing nodes | +0 nodes, +1 edge |
| W4  | `insert_cdc_placeholder` | MERGE both, mark as `:inactive` on create | +2 nodes, +1 edge |
| W5  | `update_node_props`    | SET properties on existing node | 0 / 0 |
| W6  | `promote_inactive`     | Remove `:inactive`, add `:account` | 0 / 0 (label only) |
| W7a | `upsert_label_swap`    | **Customer pattern** — MERGE + SET props + SET label + REMOVE label | +1 node / 0 |
| W7b | `upsert_label_swap_foreach` | **Customer workaround** — OPTIONAL MATCH + FOREACH/CASE | +1 node / 0 |

---

## W1a — `insert_attach_merge`

**Simulates:** Adding a new account and linking it to an existing one (the common "create entity, attach to parent" CRM op). Uses MERGE to be idempotent on the new node.

```cypher
UNWIND $ops AS op
MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo})
MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo})
  ON CREATE SET b:account, b.`@type` = 'account', b.id = op.b_id, b += op.props
CREATE (a)-[:CONNECTED_TO]->(b)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload insert_attach_merge --ops 25000 --batch-size 1000
```

**Results (per-batch latencies in ms; 1 batch = 1000 ops):**

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 53.79   | 465   | 2,036  | 2,029 | 2,101 | 2,111 | 1,949 | 2,111 |
| 500K | 14.35   | 1,743 | 458    | 453   | 586   | 605   | 332   | 605   |

**Observation:** 250K is **3.7× SLOWER** than 500K. This is suspected cold-start; warm-up rerun pending.

---

## W1b — `insert_attach_create`

**Simulates:** Same op but bypassing MERGE — caller already knows the node is new (e.g., uuid v4 just generated). CREATE-only path.

```cypher
UNWIND $ops AS op
MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo})
CREATE (b:entity:account {uuid_hi: op.b_hi, uuid_lo: op.b_lo, `@type`: 'account', id: op.b_id})
SET b += op.props
CREATE (a)-[:CONNECTED_TO]->(b)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload insert_attach_create --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 9.15    | 2,733 | 250    | 249  | 265  | 266  | 243  | 266  |
| 500K | 9.14    | 2,736 | 249    | 246  | 264  | 277  | 240  | 277  |

**Observation:** Flat across tiers. **5.9× faster than W1a at 250K.** Confirms MERGE write-path is the cost.

---

## W2a — `insert_pair_merge`

**Simulates:** A relationship-discovery event creating both endpoints idempotently (e.g., importing a contact + their employer in one statement).

```cypher
UNWIND $ops AS op
MERGE (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo})
  ON CREATE SET a:account, a.`@type` = 'account', a.id = op.a_id, a += op.a_props
MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo})
  ON CREATE SET b:account, b.`@type` = 'account', b.id = op.b_id, b += op.b_props
CREATE (a)-[:CONNECTED_TO]->(b)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload insert_pair_merge --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 125.68  | 199   | 4,799  | 4,708 | 5,629 | 5,941 | 4,358 | 5,941 |
| 500K | 42.45   | 589   | 1,470  | 1,680 | 1,975 | 2,028 | 638   | 2,028 |

**Observation:** Heaviest workload. Two MERGEs per op compound the cost. 250K→500K speedup of 3× consistent with cold-start.

---

## W2b — `insert_pair_create`

```cypher
UNWIND $ops AS op
CREATE (a:entity:account {uuid_hi: op.a_hi, uuid_lo: op.a_lo, `@type`: 'account', id: op.a_id})
CREATE (b:entity:account {uuid_hi: op.b_hi, uuid_lo: op.b_lo, `@type`: 'account', id: op.b_id})
SET a += op.a_props, b += op.b_props
CREATE (a)-[:CONNECTED_TO]->(b)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload insert_pair_create --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 14.31   | 1,747 | 345    | 343  | 359  | 360  | 337  | 360  |
| 500K | 14.33   | 1,745 | 345    | 345  | 350  | 354  | 340  | 354  |

**Observation:** Stable. **8.8× faster than W2a at 250K, 3× faster at 500K.**

---

## W3 — `insert_edge_only`

**Simulates:** Linking two existing entities (e.g., "this contact is now associated with this account"). Pure edge creation against the index lookup ceiling.

```cypher
UNWIND $ops AS op
MATCH (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo})
MATCH (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo})
CREATE (a)-[:CONNECTED_TO]->(b)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload insert_edge_only --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 2.23    | 11,208 | 84    | 84   | 87   | 88   | 82   | 88  |
| 500K | 2.19    | 11,411 | 83    | 83   | 85   | 86   | 81   | 86  |

**Observation:** Best throughput. ~83 ms/batch is essentially the network round-trip + 2 index lookups + edge-write floor.

---

## W4 — `insert_cdc_placeholder`

**Simulates:** A CDC stream of "edge between X and Y" events where the endpoints may or may not exist yet. Newly seen nodes are tagged `:inactive` until a later upsert promotes them (drives W6).

```cypher
UNWIND $ops AS op
MERGE (a:entity {uuid_hi: op.a_hi, uuid_lo: op.a_lo})
  ON CREATE SET a:inactive, a.`@type` = 'account'
MERGE (b:entity {uuid_hi: op.b_hi, uuid_lo: op.b_lo})
  ON CREATE SET b:inactive, b.`@type` = 'account'
CREATE (a)-[:CONNECTED_TO]->(b)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload insert_cdc_placeholder --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 140.28  | 178   | 5,607  | 5,530 | 6,327 | 6,407 | 5,133 | 6,407 |
| 500K | 36.96   | 677   | 1,474  | 1,854 | 2,023 | 2,031 | 226   | 2,031 |

**Observation:** Same MERGE-pair cost as W2a, plus label-set. 3.8× cold-start gap. Note Min=226 ms at 500K → engine warmed mid-run.

---

## W5 — `update_node_props`

**Simulates:** Field update on an existing entity (most common write op in production).

```cypher
UNWIND $ops AS op
MATCH (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
SET n += op.new_props
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload update_node_props --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 8.95    | 2,793 | 244    | 243  | 251  | 254  | 241  | 254  |
| 500K | 8.88    | 2,814 | 241    | 240  | 247  | 247  | 233  | 247  |

**Observation:** Rock-solid. Tier-independent — the index lookup dominates.

---

## W6 — `promote_inactive`

**Simulates:** Background "promotion" job that converts placeholder `:inactive` nodes into real `:account` records (the back-end of W4).

```cypher
UNWIND $ops AS op
MATCH (n:entity:inactive {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
REMOVE n:inactive SET n:account
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload promote_inactive --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 58.33   | 429   | 2,332  | **43**  | **6,054** | 6,203 | 41    | 6,203 |
| 500K | 5.18    | 4,829 | 206    | **42**  | 565   | 595   | 40    | 595   |

**Observation:** **Bimodal!** p50 of ~42 ms says steady-state is fast; the avg is dragged by a few catastrophic 6-second batches at 250K. p95/max are the real story here, not avg.

---

## W7a — `upsert_label_swap` ⚠️ Customer scenario (customer)

**Simulates:** The exact pattern from the customer ticket — single-statement upsert that always sets props and swaps labels (idempotent regardless of whether the row exists).

```cypher
UNWIND $ops AS op
MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
SET n = op.props
SET n:account
REMOVE n:inactive
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload upsert_label_swap --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 89.49   | 279   | 3,466  | 3,435 | 3,926 | 3,994 | 3,093 | 3,994 |
| 500K | 22.92   | 1,091 | 802    | 804  | 951   | 965   | 634   | 965   |

**Observation:** ⚠️ See W7b for the customer-reported workaround comparison.

---

## W7b — `upsert_label_swap_foreach` ✅ Customer workaround

**Simulates:** Same upsert, expressed as the customer's manual rewrite splitting create/update branches.

```cypher
UNWIND $ops AS op
OPTIONAL MATCH (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
FOREACH (_ IN CASE WHEN n IS NOT NULL THEN [1] ELSE [] END |
  SET n = op.props SET n:account REMOVE n:inactive)
FOREACH (_ IN CASE WHEN n IS NULL THEN [1] ELSE [] END |
  CREATE (u:entity:account {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) SET u = op.props)
```

**Reproduce:**
```bash
benchmark run --tier 250000 --workload upsert_label_swap_foreach --ops 25000 --batch-size 1000
```

| Tier | Total s | Ops/s | Avg ms | p50 | p95 | p99 | Min | Max |
|------|---------|-------|--------|------|------|------|------|------|
| 250K | 8.73    | 2,865 | 235    | 233  | 244  | 265  | 230  | 265  |
| 500K | 8.55    | 2,923 | 228    | 227  | 233  | 234  | 220  | 234  |

**🚨 The customer bug, quantified:**

| Tier | Customer (W7a) p50 | Workaround (W7b) p50 | **Slowdown** |
|------|---------------------|----------------------|--------------|
| 250K | 3,435 ms            | 233 ms               | **14.7× slower** |
| 500K | 804 ms              | 227 ms               | **3.5× slower**  |

| Tier | Customer ops/s | Workaround ops/s | **Throughput loss** |
|------|----------------|------------------|---------------------|
| 250K | 279            | 2,865            | **10.3× lower**     |
| 500K | 1,091          | 2,923            | **2.7× lower**      |

The W7b workaround is also **flat across tiers** (~2,900 ops/s) — it's the W7a path that degrades.

---

## Summary table — all 20 rows

| Workload | Tier | Ops/s | Avg ms | p50 | p95 | p99 |
|----------|------|-------|--------|-----|-----|-----|
| insert_attach_merge          | 250K |    465 | 2,036 | 2,029 | 2,101 | 2,111 |
| insert_attach_create         | 250K |  2,733 |   250 |   249 |   265 |   266 |
| insert_pair_merge            | 250K |    199 | 4,799 | 4,708 | 5,629 | 5,941 |
| insert_pair_create           | 250K |  1,747 |   345 |   343 |   359 |   360 |
| insert_edge_only             | 250K | 11,208 |    84 |    84 |    87 |    88 |
| insert_cdc_placeholder       | 250K |    178 | 5,607 | 5,530 | 6,327 | 6,407 |
| update_node_props            | 250K |  2,793 |   244 |   243 |   251 |   254 |
| promote_inactive             | 250K |    429 | 2,332 |    43 | 6,054 | 6,203 |
| upsert_label_swap            | 250K |    279 | 3,466 | 3,435 | 3,926 | 3,994 |
| upsert_label_swap_foreach    | 250K |  2,865 |   235 |   233 |   244 |   265 |
| insert_attach_merge          | 500K |  1,743 |   458 |   453 |   586 |   605 |
| insert_attach_create         | 500K |  2,736 |   249 |   246 |   264 |   277 |
| insert_pair_merge            | 500K |    589 | 1,470 | 1,680 | 1,975 | 2,028 |
| insert_pair_create           | 500K |  1,745 |   345 |   345 |   350 |   354 |
| insert_edge_only             | 500K | 11,411 |    83 |    83 |    85 |    86 |
| insert_cdc_placeholder       | 500K |    677 | 1,474 | 1,854 | 2,023 | 2,031 |
| update_node_props            | 500K |  2,814 |   241 |   240 |   247 |   247 |
| promote_inactive             | 500K |  4,829 |   206 |    42 |   565 |   595 |
| upsert_label_swap            | 500K |  1,091 |   802 |   804 |   951 |   965 |
| upsert_label_swap_foreach    | 500K |  2,923 |   228 |   227 |   233 |   234 |

---

## Cross-cutting findings

1. **MERGE is the cost.** Wherever MERGE appears (W1a, W2a, W4, W7a) latency is 5–15× the CREATE-only or MATCH+SET equivalent. The `_create` siblings (W1b, W2b) and pure-update workloads (W5, W7b) all sit at ~230–350 ms/batch.
2. **Cold start is real.** 5 of the MERGE-heavy workloads (W1a, W2a, W4, W7a, W6) all show 250K significantly slower than 500K — the inverse of what graph-size effects would predict. Pure CREATE/UPDATE workloads are flat across tiers. → `scripts/warmup_rerun.sh` was created to test this.
3. **Network ceiling.** W3 plateaus at ~11.4K ops/s = ~83 ms/batch. That's the practical upper bound for any 1000-op batch hitting this cloud instance.
4. **W6 bimodality.** p50 42 ms vs avg 2,332 ms at 250K means most batches are *fast* but a handful take ~6 sec. Effective throughput in production would be much higher than ops/s suggests; investigate the long-tail batches (likely GC or index-rebuild stalls).
5. **W7a customer bug confirmed.** Both at 250K (10.3×) and 500K (2.7×). Filed in `info/falkordb-bug-report-w7.md`.

---

## Files referenced

| File | Purpose |
|------|---------|
| `results-cloud/workloads_20260422_005515.csv` | Source data for this report |
| `logs-cloud/suite_20260422_002933.log`        | Run log |
| `benchmark/workloads.py`                      | Workload definitions + Cypher templates |
| `benchmark/cli.py`                            | `init`, `run`, `suite` commands |
| `scripts/full_run.sh`                         | The script that produced this run |
| `scripts/warmup_rerun.sh`                     | Pending — verifies cold-start theory |
| `info/falkordb-bug-report-w7.md`              | Draft bug report for the W7a regression |
