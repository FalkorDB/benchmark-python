#!/usr/bin/env bash
# Full benchmark run: init two tiers once, then run all workloads against them.
# Usage:
#   FALKOR_HOST=... FALKOR_USER=... FALKOR_PASS=... ./scripts/full_run.sh
set -euo pipefail

: "${FALKOR_HOST:?FALKOR_HOST not set}"
: "${FALKOR_USER:=falkordb}"
: "${FALKOR_PASS:?FALKOR_PASS not set}"
PORT="${FALKOR_PORT:-6379}"

TIERS=(250000 500000)
INIT_BATCH="${INIT_BATCH:-10000}"
RUN_OPS="${RUN_OPS:-25000}"
RUN_BATCH="${RUN_BATCH:-1000}"

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
TS="$(date -u +%Y%m%d_%H%M%S)"

echo "============================================================"
echo " FalkorDB benchmark — full run"
echo " Host:       $FALKOR_HOST:$PORT"
echo " Tiers:      ${TIERS[*]}"
echo " Init batch: $INIT_BATCH"
echo " Run ops:    $RUN_OPS, batch $RUN_BATCH"
echo "============================================================"

echo
echo "--- ping ---"
redis-cli -h "$FALKOR_HOST" -p "$PORT" --user "$FALKOR_USER" --pass "$FALKOR_PASS" \
  --no-auth-warning PING

echo
echo "--- existing graphs ---"
redis-cli -h "$FALKOR_HOST" -p "$PORT" --user "$FALKOR_USER" --pass "$FALKOR_PASS" \
  --no-auth-warning GRAPH.LIST || true

# Phase 1: init each tier once. ensure_init is idempotent — it skips a graph
# whose node count already matches the requested size, so re-running is safe.
for T in "${TIERS[@]}"; do
  echo
  echo "============================================================"
  echo " INIT tier=$T  (one-shot, idempotent)"
  echo "============================================================"
  benchmark init \
    --host "$FALKOR_HOST" --port "$PORT" \
    --username "$FALKOR_USER" --password "$FALKOR_PASS" \
    --tier "$T" --batch-size "$INIT_BATCH" \
    2>&1 | tee "$LOG_DIR/init_${T}_${TS}.log"
done

# Phase 2: benchmark all workloads × all tiers, no init reloading.
TIER_FLAGS=()
for T in "${TIERS[@]}"; do
  TIER_FLAGS+=(--tiers "$T")
done

echo
echo "============================================================"
echo " SUITE: ${TIERS[*]}  (skip-init, all 10 workloads)"
echo "============================================================"
benchmark suite \
  --host "$FALKOR_HOST" --port "$PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  "${TIER_FLAGS[@]}" \
  --skip-init \
  --ops "$RUN_OPS" --batch-size "$RUN_BATCH" \
  2>&1 | tee "$LOG_DIR/suite_${TS}.log"

echo
echo "Done. Results saved under results/ and logs under $LOG_DIR/."
