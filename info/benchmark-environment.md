# Benchmark Environment

This document captures the canonical environment used for the FalkorDB CRM
benchmark runs published in `info/benchmark-results-detailed.md` and referenced
by `info/falkordb-bug-report-w7.md`. All cloud-result CSVs/logs in
`results-cloud/` and `logs-cloud/` were produced against this setup unless
explicitly noted otherwise.

## Topology

```
   ┌──────────────────────┐    Redis RESP / TCP     ┌────────────────────────────┐
   │  Client (driver)     │ ──────────────────────► │ FalkorDB Cloud (standalone)│
   │  AWS EC2 c4.xlarge   │                          │ AWS EC2 c6i.8xlarge        │
   │  Region: us-east-2   │                          │ Region: us-east-2          │
   └──────────────────────┘                          └────────────────────────────┘
```

## Client

| Property        | Value                                       |
|-----------------|---------------------------------------------|
| Provider        | AWS EC2                                     |
| Instance type   | **c4.xlarge** (4 vCPU, 7.5 GiB RAM)         |
| Region / AZ     | us-east-2                                   |
| OS              | Ubuntu                                      |
| Python          | 3.10+                                       |
| Driver          | `falkordb-py` (Redis protocol)              |
| Concurrency     | Single client, serial batches               |
| TLS             | Disabled                                    |

## Server (FalkorDB)

| Property         | Value                                                  |
|------------------|--------------------------------------------------------|
| Deployment       | **FalkorDB Cloud — standalone (single node, no replica)** |
| Host instance    | **AWS EC2 c6i.8xlarge** (32 vCPU, 64 GiB RAM)          |
| Region           | us-east-2                                              |
| Endpoint         | `r-ercqm6xbqm.instance-if8kk23ls.hc-2uaqqpjgg.us-east-2.aws.f2e0a955bb84.cloud:6379` |
| Auth             | username `falkordb`                                    |
| TLS              | Disabled                                               |
| Persistence      | Cloud default (managed)                                |

> Note: an earlier, smaller cloud instance (`r-ercqm6xbqm.instance-qb12n22h7...`)
> was used for the very first probe runs and proved too small. All published
> results in this repo come from the **c6i.8xlarge** instance above.

## Network

- Same region (us-east-2), client and server in AWS, public endpoint.
- Network round-trip is the practical floor for batched ops — see W3
  (`insert_edge_only`) at ~83 ms/batch in the results doc.

## Run parameters

| Parameter      | Value                                       |
|----------------|---------------------------------------------|
| Init batch     | 10,000 ops/batch                            |
| Workload ops   | 25,000 per workload                         |
| Workload batch | 1,000 ops/batch (= 25 batches per workload) |
| Tiers          | 250,000 and 500,000 init nodes              |
| Indexed        | Yes — composite index on `:entity (uuid_hi, uuid_lo)` |
| Throttle       | None (`--throttle-ms 0`)                    |

## Reproducer

```bash
export FALKOR_HOST='r-ercqm6xbqm.instance-if8kk23ls.hc-2uaqqpjgg.us-east-2.aws.f2e0a955bb84.cloud'
export FALKOR_PORT=6379
export FALKOR_USER='falkordb'
export FALKOR_PASS='<set-me>'

./scripts/full_run.sh
```

`full_run.sh` does an idempotent `init` for each tier then runs
`benchmark suite --skip-init` against the existing graphs. Output goes to
`results/` and `logs/`; the published copies are mirrored under
`results-cloud/` and `logs-cloud/`.
