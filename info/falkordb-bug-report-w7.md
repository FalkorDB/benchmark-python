---
title: "MERGE + SET label + REMOVE label upsert is 10× slower than FOREACH/CASE workaround on indexed graphs"
labels: [performance, query-planner, MERGE]
---

## Summary

Reproduces a customer-reported regression (Reevo / Alex). The single-statement upsert
pattern that combines `MERGE` with an unconditional `SET label` and `REMOVE label`
runs **2.7× to 10.3× slower** than a logically-equivalent `OPTIONAL MATCH + FOREACH/CASE`
rewrite on the same data, on the same instance.

The slow path's per-batch p50 latency varies wildly with tier size in a way the
fast path does not, suggesting the cost is in query planning or in the
`SET label` / `REMOVE label` write path — **not** in the index lookup.

## Reproducer

Composite range index on `(uuid_hi, uuid_lo)` for `:entity`. Graph pre-loaded with
N `:entity:account` nodes via `MERGE` (uses the same composite key).

### Slow query (customer pattern)
```cypher
UNWIND $ops AS op
MERGE (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
SET n = op.props
SET n:account
REMOVE n:inactive
```

### Fast query (FOREACH workaround — same effect)
```cypher
UNWIND $ops AS op
OPTIONAL MATCH (n:entity {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo})
FOREACH (_ IN CASE WHEN n IS NOT NULL THEN [1] ELSE [] END |
  SET n = op.props SET n:account REMOVE n:inactive)
FOREACH (_ IN CASE WHEN n IS NULL THEN [1] ELSE [] END |
  CREATE (u:entity:account {uuid_hi: op.uuid_hi, uuid_lo: op.uuid_lo}) SET u = op.props)
```

Both invoked with `params={"ops": [<batch of 1000 ops>]}` for 25 batches × 1000 ops
= 25K total ops per measurement. Ops target a fresh uuid range above the init size,
so every op is an **insert** path on the first run.

## Numbers (25K ops/run, batch size 1000, FalkorDB cloud — production sizing)

| Tier | Slow query (customer) | Fast query (workaround) | Slow / Fast |
|---|---:|---:|---:|
| 250K nodes | **279 ops/s** · p50 = 3,435 ms | **2,865 ops/s** · p50 = 233 ms | **10.3×** |
| 500K nodes | **1,091 ops/s** · p50 = 804 ms | **2,923 ops/s** · p50 = 227 ms | **2.7×** |

The fast query is **flat across tiers** (~2,900 ops/s, p50 ~230ms). The slow query
varies by ~4× between adjacent tiers in the same run, even though both queries
operate on the same underlying graphs and target the same uuid keys.

## Why this matters

This is the upsert pattern customers reach for naturally — `MERGE` on the natural
key, then unconditionally write the latest property snapshot and adjust labels.
It is also exactly the pattern reported by Alex (Reevo) in their CDC ingestion
where `graph.write` time was 9.1× slower on insert vs update for the same query.

## Hypothesis (please confirm or refute)

The unconditional `SET label` / `REMOVE label` is being evaluated **on the create
path** as well as the match path, and either:

a) the planner re-evaluates the index on each `SET label` (causing index
   churn during the same statement that just inserted into it), or
b) the label-set code path re-resolves the node by key rather than reusing
   the bound variable.

The FOREACH variant short-circuits this by partitioning the create vs update
paths explicitly.

## Reproduction artifacts

Attach:
- `results-cloud/workloads_20260422_005515.csv` — full 20-row result table
- `results-cloud/benchmark_20260422_005515.json` — per-batch timings incl. p50/p95/p99/min/max
- `logs-cloud/suite_20260422_002933.log` — run log

Repo: <https://github.com/FalkorDB/benchmark-python> (branch `feat/crm-aligned-tiers`).
Workloads `upsert_label_swap` (slow) and `upsert_label_swap_foreach` (fast)
defined in `benchmark/workloads.py`.

## Asks

1. Confirm whether the index-rewrite work in flight addresses this pattern.
2. If yes, when can we re-test against a build that has it?
3. If no, can we get a `PROFILE` of both queries on the same 250K graph to
   see where the 10× goes?
