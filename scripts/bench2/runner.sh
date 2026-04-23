#!/usr/bin/env bash
# bench2 full runner — runs both B1 (no-index) and B2 (indexed) end-to-end.
set -euo pipefail

HOST="${FALKOR_HOST:-localhost}"
PORT="${FALKOR_PORT:-6379}"
NODES="${BENCH2_NODES:-50000}"
OPS="${BENCH2_OPS:-25000}"
BATCH="${BENCH2_BATCH:-100}"
WARMUP="${BENCH2_WARMUP:-10}"
GRAPH_PREFIX="${BENCH2_GRAPH_PREFIX:-bench2}"
RESULTS_DIR="${BENCH2_RESULTS_DIR:-results-b2}"

ARGS=(--host "$HOST" --port "$PORT"
      --graph-prefix "$GRAPH_PREFIX"
      --nodes "$NODES"
      --ops "$OPS"
      --batch-size "$BATCH"
      --warmup-batches "$WARMUP"
      --results-dir "$RESULTS_DIR")

if [[ -n "${FALKOR_USER:-}" ]]; then ARGS+=(--username "$FALKOR_USER"); fi
if [[ -n "${FALKOR_PASS:-}" ]]; then ARGS+=(--password "$FALKOR_PASS"); fi

python -m bench2.cli full "${ARGS[@]}"
