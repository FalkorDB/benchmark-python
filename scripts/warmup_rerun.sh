#!/usr/bin/env bash
# Warm-up vs steady-state re-run.
#
# Suspicion: in the previous full_run.sh, the 250K results looked dramatically
# slower than 500K for MERGE-heavy workloads — likely because the cloud
# instance was cold when 250K ran. This script:
#   1. Runs a throwaway "warm-up" pass at 250K (results discarded).
#   2. Runs the *real* measured pass at 250K.
#   3. Then runs 500K.
# Comparing run #2 of 250K against the original 250K row tells us how much of
# the gap was cold-start vs intrinsic.
#
# Inits are reused from a prior `full_run.sh` execution.
set -euo pipefail

: "${FALKOR_HOST:?FALKOR_HOST not set}"
: "${FALKOR_USER:=falkordb}"
: "${FALKOR_PASS:?FALKOR_PASS not set}"
PORT="${FALKOR_PORT:-6379}"

RUN_OPS="${RUN_OPS:-25000}"
RUN_BATCH="${RUN_BATCH:-1000}"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
TS="$(date -u +%Y%m%d_%H%M%S)"

echo "============================================================"
echo " Warm-up vs steady-state re-run"
echo " Host:  $FALKOR_HOST:$PORT"
echo " ops=$RUN_OPS  batch=$RUN_BATCH"
echo "============================================================"

# --- Warm-up pass (results not analyzed; we just want the cache hot) ---
echo
echo "--- WARM-UP @ 250K (discarded) ---"
benchmark suite \
  --host "$FALKOR_HOST" --port "$PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --tiers 250000 --skip-init \
  --ops "$RUN_OPS" --batch-size "$RUN_BATCH" \
  --no-save --no-csv \
  2>&1 | tee "$LOG_DIR/warmup_250k_${TS}.log"

# --- Real measured pass at 250K (this is the comparison row) ---
echo
echo "--- MEASURED @ 250K (after warm-up) ---"
benchmark suite \
  --host "$FALKOR_HOST" --port "$PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --tiers 250000 --skip-init \
  --ops "$RUN_OPS" --batch-size "$RUN_BATCH" \
  2>&1 | tee "$LOG_DIR/measured_250k_${TS}.log"

# --- Real measured pass at 500K (cache is warm from prior runs) ---
echo
echo "--- MEASURED @ 500K ---"
benchmark suite \
  --host "$FALKOR_HOST" --port "$PORT" \
  --username "$FALKOR_USER" --password "$FALKOR_PASS" \
  --tiers 500000 --skip-init \
  --ops "$RUN_OPS" --batch-size "$RUN_BATCH" \
  2>&1 | tee "$LOG_DIR/measured_500k_${TS}.log"

echo
echo "Done. Compare the latest two timestamped CSVs under results/ ."
