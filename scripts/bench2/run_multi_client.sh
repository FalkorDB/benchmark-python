#!/usr/bin/env bash
# Two-client matrix runner for bench2.
#
# Inits a shared graph from CLIENT_A, then launches the same workload
# from CLIENT_A and CLIENT_B simultaneously over SSH against disjoint
# --start-id ranges. Results land in ./results-cloud-multi/<tag>/.
#
# Required env:
#   FALKOR_HOST, FALKOR_PORT, FALKOR_USER, FALKOR_PASS
#   CLIENT_A, CLIENT_B            ssh user@host for each client
#   SSH_KEY                       path to ssh private key
#
# Args:
#   $1 TAG          e.g. t1_1m
#   $2 SHAPE        init shape (e.g. add_new_node, add_new_node_active)
#   $3 WORKLOAD     bench workload (e.g. add_new_node, upsert_w7, delete_by_uuid)
#   $4 INIT_SIZE    nodes to init (e.g. 1000000)
#   $5 OPS_PER_CLIENT  e.g. 25000
#   $6 START_ID_A   bench start id for client A (e.g. INIT_SIZE for create-tests, 0 for delete)
#   $7 START_ID_B   bench start id for client B (e.g. INIT_SIZE+OPS_PER_CLIENT)

set -euo pipefail

TAG=$1
SHAPE=$2
WORKLOAD=$3
INIT_SIZE=$4
OPS=$5
START_A=$6
START_B=$7

GRAPH=multi_${TAG}
OUT=./results-cloud-multi/${TAG}
mkdir -p "$OUT"

SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"
TLS_FLAG="${FALKOR_TLS:+--tls}"
REMOTE_ENV="export FALKOR_HOST=$FALKOR_HOST FALKOR_PORT=$FALKOR_PORT FALKOR_USER=$FALKOR_USER FALKOR_PASS=$FALKOR_PASS;"

echo "================ ${TAG} ================"
echo "graph=$GRAPH  shape=$SHAPE  workload=$WORKLOAD"
echo "init=$INIT_SIZE  ops/client=$OPS"
echo "A: --start-id $START_A    B: --start-id $START_B"
echo

echo "[init] on CLIENT_A ($CLIENT_A)..."
$SSH "$CLIENT_A" "$REMOTE_ENV cd ~/benchmark-python && source .venv/bin/activate && \
  python -u -m bench2.cli init --host \$FALKOR_HOST --port \$FALKOR_PORT $TLS_FLAG \
    --username \$FALKOR_USER --password \$FALKOR_PASS \
    --graph $GRAPH --shape $SHAPE --nodes $INIT_SIZE --batch-size 1000" \
  2>&1 | tee "$OUT/init.log"

echo
echo "[bench] firing both clients in parallel..."

run_client() {
  local host=$1; local label=$2; local start=$3; local logfile=$4
  $SSH "$host" "$REMOTE_ENV cd ~/benchmark-python && source .venv/bin/activate && \
    python -u -m bench2.cli run --host \$FALKOR_HOST --port \$FALKOR_PORT $TLS_FLAG \
      --username \$FALKOR_USER --password \$FALKOR_PASS \
      --graph $GRAPH --workload $WORKLOAD --name ${WORKLOAD}_${TAG}_${label} \
      --start-id $start --ops $OPS --batch-size 1000 --warmup-batches 10" \
    2>&1 | tee "$logfile"
}

run_client "$CLIENT_A" "A" "$START_A" "$OUT/run_a.log" &
PID_A=$!
run_client "$CLIENT_B" "B" "$START_B" "$OUT/run_b.log" &
PID_B=$!

wait $PID_A; RC_A=$?
wait $PID_B; RC_B=$?

echo
echo "================ DONE ${TAG} ================"
echo "client A rc=$RC_A   client B rc=$RC_B"

# Tiny aggregator: extract per-client ops/s and avg ms
python3 <<PY
import re
def grab(path):
    with open(path) as f:
        for line in f:
            m = re.search(r'\\[run\\] \\S+: ([\\d,]+) ops/s\\s+avg=([\\d.]+) ms/op', line)
            if m: return float(m.group(1).replace(',','')), float(m.group(2))
    return None, None
a_ops, a_ms = grab("$OUT/run_a.log")
b_ops, b_ms = grab("$OUT/run_b.log")
if a_ops and b_ops:
    print(f"A: {a_ops:>8,.0f} ops/s  avg={a_ms:.4f} ms/op")
    print(f"B: {b_ops:>8,.0f} ops/s  avg={b_ms:.4f} ms/op")
    print(f"Σ: {a_ops+b_ops:>8,.0f} ops/s  (combined throughput)")
PY
