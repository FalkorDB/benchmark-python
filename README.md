# FalkorDB Population Benchmark

A Python benchmark tool that measures FalkorDB data population performance across
increasing graph sizes with configurable batch sizes.

## Growth Tiers

| Tier | Nodes | Properties/Node |
|------|-------|-----------------|
| 1    | 10,000 | 100 |
| 2    | 50,000 | 100 |
| 3    | 100,000 | 100 |
| 4    | 500,000 | 100 |

## Quick Start

```bash
# Start FalkorDB
docker run --rm -p 6379:6379 falkordb/falkordb

# Install
pip install -e .

# Run population benchmark (all tiers, batch size 500)
benchmark populate --batch-size 500

# Run a single tier
benchmark populate --tiers 10000 --batch-size 1000

# Custom host/port
benchmark populate --host localhost --port 6379 --batch-size 500
```

## Output

Results are printed as a rich terminal table showing per-tier:
- Total time
- Throughput (nodes/sec)
- Batch latency percentiles (p50, p90, p95, p99)

Results are also saved to `results/` as JSON.
