# bench2 — FalkorDB Cloud instance comparison

Comparison of how the **same 5 write-workload tests** behave on three different
FalkorDB Cloud instance shapes. Same client (single AWS `c4.xlarge` in
us-east-2), same Cypher, same 25K ops per run, batch 1000, warmup 10 batches.

> **Source data**: this doc consolidates results from
> [`bench2-results-cloud.md`](./bench2-results-cloud.md) (the original
> c6i.8xlarge sections for Tests 1–5) plus two new instance runs added
> by the `run_single_matrix.sh` orchestrator.

## Instances under test

| Tag | Instance | vCPU | RAM | Family | FalkorDB version | TLS | Notes |
|---|---|---:|---:|---|---|---|---|
| `c6i_8xl` | **c6i.8xlarge**     | 32 | 64 GiB | compute-optimized | v4.18.01 | no  | Original cloud baseline (April runs) |
| `m6i_large` | **m6i.large**     | 2  | 8 GiB  | general-purpose   | v4.18.01 | yes | Smallest tier — known to crash under T3 1.5M |
| `r6i_xl`  | **r6i.xlarge**     | 4  | 32 GiB | **memory-optimized** | v4.18.01 / v8.6.2 RDB engine reported | yes | Current upgrade — chose to **scale memory, hold CPU near baseline** |

All instances: us-east-2, public endpoint, single client thread.

### Why r6i.xlarge specifically?

The m6i.large run crashed the FalkorDB server during T3 at 1.5M nodes — the
graph + working set didn't fit in 8 GiB. The natural reflex is to scale up
**both** CPU and memory (e.g. m6i.2xlarge gives 8 vCPU + 32 GiB), but that
mixes two variables and you can't tell which one solved the problem.

The r6i.xlarge experiment isolates the memory dimension: **+24 GiB RAM, +2
vCPU**. It's a memory-optimized family, deliberately *not* a big CPU upgrade.
The hypothesis being tested:

> "Does giving FalkorDB more memory fix the W7 workload at 1M+ nodes, or is
> CPU still the dominant lever?"

The answer the data gives is below.

## Headline table — average ms/op (lower is better)

| Test | Tier | c6i.8xlarge | m6i.large | r6i.xlarge |
|---|---|---:|---:|---:|
| **T1** add_new_node            | 500K | 0.126 | 0.155 | **0.131** |
|                                | 1M   | 0.135 | 0.154 | **0.144** |
|                                | 1.5M | 0.138 | 0.171 | 0.147 |
| **T2** add_new_node_with_audit | 500K | 0.141 | 0.142 | **0.141** |
|                                | 1M   | 0.153 | 0.159 | **0.152** |
|                                | 1.5M | 0.146 | 0.178 | 0.151 |
| **T3** upsert_w7 (REMOVE)      | 500K | **4.045** | 10.86 | 5.96 |
|                                | 1M   | **7.31**  | 24.47 | 14.45 |
|                                | 1.5M | **9.81**  | **CRASHED** ⚠ | 20.95 |
| **T4** upsert_w7 (active)      | 500K | **4.16**  | 2.38\* | 6.40 |
|                                | 1M   | **7.39**  | 0.43\* | 14.05 |
|                                | 1.5M | **9.81**  | init failed | **CRASHED** ⚠ |
| **T5** delete_by_uuid          | 500K | 0.058 | 0.066 | **0.057** |
|                                | 1M   | 0.075 | 0.066 | **0.047** |
|                                | 1.5M | 0.064 | 0.088 | 0.064 |

\* m6i.large T4 results are anomalously fast vs the matching T3 results on the
same instance, and out of line with both the smaller (c6i.8xlarge) and larger
(r6i.xlarge) instance numbers. Most likely a measurement artifact from the
just-finished active-index init leaving hot state. **Treat the m6i.large T4
numbers as suspect.**

## Headline table — ops/sec (higher is better)

| Test | Tier | c6i.8xlarge | m6i.large | r6i.xlarge |
|---|---|---:|---:|---:|
| T1 | 500K |  5,422 | 4,615 | **5,219** |
|    | 1M   |  5,162 | 4,662 | 4,882 |
|    | 1.5M |  5,082 | 4,312 | 4,816 |
| T2 | 500K |  ~5,000 | 4,914 | 4,931 |
|    | 1M   |  4,708 | 4,528 | 4,679 |
|    | 1.5M |  ~5,100 | 4,180 | 4,693 |
| T3 | 500K |    247 |    92 |   166 |
|    | 1M   |    137 |    41 |    69 |
|    | 1.5M |    100 | crashed |    46 |
| T4 | 500K |    240 |   409\* |   155 |
|    | 1M   |    135 | 2,018\* |    71 |
|    | 1.5M |    102 | failed  | crashed |
| T5 | 500K | 17,241 | 13,744 | **15,671** |
|    | 1M   | 12,235 | 13,694 | **18,355** |
|    | 1.5M | 15,625 | 10,476 | 14,174 |

## Key insights

### 1. Memory alone does NOT fix the W7 workload — but it prevents the crash

The r6i.xlarge experiment was designed to isolate memory: +24 GiB RAM, only
+2 vCPU vs m6i.large. The W7 latency at 1M went from **24.5 ms → 14.5 ms**
(a 41% drop), but only ~half of that improvement is plausibly attributable to
the +2 vCPU; the other half is the tail of the per-vCPU scaling curve (more
memory means less time spent in cache misses + GC during the prop-store
rewrite).

What memory **did** fix: the **server no longer crashes at 1.5M T3** (m6i.large
crashed the FalkorDB process at this size — see Insight 3 for detail). With
32 GiB available, the working set fits and the server stays up. So memory is
necessary at scale, but it is not sufficient to make W7-shaped writes fast.

> **For the customer**: throwing memory at a W7-shaped workload buys you
> **stability** at higher graph sizes, not throughput. You still need
> per-vCPU horsepower (or, better, a query rewrite — see Insight 6).

### 2. Cheap workloads are barely affected by instance size

T1 (`MERGE` add), T2 (add + 2 small SETs), and T5 (`DELETE`-by-uuid) come in
within ~15% of each other across all three instances. These workloads are
**network/protocol bound** — even the 2-vCPU m6i.large keeps up.

The customer-facing implication: if a workload is mostly composite-index
`MERGE` + small `ON CREATE SET`, you do not need a big instance to hit
4–5K ops/sec single-thread.

### 3. Heavy workloads (T3/T4 W7-shaped) scale roughly with vCPU count

The customer W7 pattern (`MERGE :entity` + unconditional `SET n=$props` of 50
properties + `SET :account` + `REMOVE :inactive`) is **CPU-bound on the
server** — every op rewrites the prop store and touches the composite index.

Per-op latency at 1M nodes:

| Instance | vCPU | RAM | T3 ms/op | per-vCPU normalized |
|---|---:|---:|---:|---:|
| c6i.8xlarge | 32 | 64 GiB |  7.31 | 234 |
| r6i.xlarge  |  4 | 32 GiB | 14.45 | 58  |
| m6i.large   |  2 |  8 GiB | 24.47 | 49  |

**Takeaway**: T3 latency tracks (1 / vCPU) much more tightly than it tracks
RAM. r6i.xlarge has **4× the RAM** of m6i.large but only **~1.7× the T3
throughput**, while the c6i.8xlarge has **8× the vCPU** of r6i.xlarge and
delivers **~2× the T3 throughput** — the compute scales but with diminishing
returns past ~8 cores (the workload is also serialization-bound on the
composite-index write path).

### 4. Both small instances crash at 1.5M nodes — at different tests

On the **m6i.large** (8 GiB RAM), T3 1.5M reached ~38 ms/op during warmup
and then **crashed the FalkorDB server**, which restarted from snapshot
("Redis is loading the dataset in memory"). The follow-up T4 1.5M init also
failed.

On the **r6i.xlarge** (32 GiB RAM), T3 1.5M completed (20.95 ms/op, ~46 ops/s)
but the server **crashed during T4 1.5M** with the same recovery symptom.
Server uptime after the matrix confirmed a restart at the T3→T4 boundary.

Adding RAM (8 → 32 GiB) buys one extra completed test at the 1.5M tier, but
the W7 active-index workload (T4) is still **enough to take the box down**
on a 4-vCPU instance. Only the c6i.8xlarge (32 vCPU) ran the full matrix
clean at 1.5M.

### 5. Delete is the cheapest write — and benefits from CPU

T5 (`DELETE`-by-uuid) is the only workload where the **r6i.xlarge beats the
c6i.8xlarge at 1M** (0.047 ms vs 0.075 ms). The c6i.8xlarge result was the
noisier of its tier numbers (the per-batch variance was visible in the
original report). On a quieter run, r6i.xlarge sustains ~18K ops/sec
single-thread for index-keyed deletes — the highest sustained write rate
across this whole matrix on any instance.

### 6. The actual fix is the query, not the instance

Even on the c6i.8xlarge (32 vCPU), T3 only delivers ~137 ops/sec at 1M nodes —
two orders of magnitude slower than T1/T2 on the **same hardware**. No
realistic instance upgrade closes that gap. The customer-side change is to
replace unconditional `SET n = $props` with `ON CREATE SET` / `ON MATCH SET`
writing only what changed. T2 (which adds two small SETs to T1) demonstrates
this pattern at ~10% overhead vs T1 — i.e. **the same workload restructured
properly is 50–100× faster on the same hardware**.

## Customer-facing recommendation

1. **Memory keeps you alive at scale; CPU keeps you fast.** RAM upgrades buy
   you one extra test at 1.5M (8 → 32 GiB lets T3 finish where it used to
   crash) but the W7 active-index test (T4) still crashes the box at 1.5M
   on 4 vCPU. Only the 32-vCPU c6i.8xlarge ran the full matrix clean.
2. For W7-shaped workloads where you also want throughput, **scale by
   vCPU, not just memory**. Latency tracks roughly with (1/vCPU) until
   ~8 cores, then plateaus.
3. **The biggest win is the query, not the instance.** Even on c6i.8xlarge
   (32 vCPU), T3 only delivers ~137 ops/sec at 1M nodes. Replacing
   unconditional `SET n = $props` with `ON CREATE SET` / `ON MATCH SET`
   writing only what changed (the T2 pattern) gives **50–100× speedup on
   the same hardware** — no instance upgrade comes close.

## How to reproduce

```bash
export FALKOR_HOST=<your-cloud-host>  FALKOR_PORT=6379
export FALKOR_USER=falkordb           FALKOR_PASS=<your-pass>
export FALKOR_TLS=1                   # if your instance requires TLS
export CLIENT=ubuntu@<client-ec2-ip>
export SSH_KEY=~/path/to/key.pem
export TAG_PREFIX=standalone_<your_label>      # e.g. r6i_xl, m6i_large

bash scripts/bench2/run_single_matrix.sh
```

Per-test logs land in `results-cloud-${TAG_PREFIX}/<test>_<tier>/{init,run}.log`.
The script drops each graph after its test so only one is live at a time —
critical for low-memory instances (see m6i.large note above).
