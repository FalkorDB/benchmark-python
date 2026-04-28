#!/usr/bin/env bash
# Single-client 5-test x 3-tier matrix for bench2.
# Inits each tier x test on a dedicated graph (so tests don't pollute each other),
# then runs the matching workload. Designed for ONE EC2 client.
#
# Required env:
#   FALKOR_HOST, FALKOR_PORT, FALKOR_USER, FALKOR_PASS
#   FALKOR_TLS=1   (optional, set to anything to enable --tls)
#   CLIENT          ssh user@host of the client
#   SSH_KEY         path to ssh private key
#
# Optional env:
#   TAG_PREFIX      prefix for graph + result dir names (e.g. "stdalone", "ha"). Default: "single"

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OPS=25000
PREFIX="${TAG_PREFIX:-single}"
TLS_FLAG="${FALKOR_TLS:+--tls}"
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"
REMOTE_ENV="export FALKOR_HOST=$FALKOR_HOST FALKOR_PORT=$FALKOR_PORT FALKOR_USER=$FALKOR_USER FALKOR_PASS=$FALKOR_PASS;"

# tier_name init_size
TIERS=(
  "500k 500000"
  "1m   1000000"
  "1_5m 1500000"
)

# test_name shape workload start_offset_kind
#   start_offset_kind = "init"  -> bench --start-id $init_size      (creates after init range)
#   start_offset_kind = "zero"  -> bench --start-id 0               (delete-from-front)
TESTS=(
  "t1   add_new_node            add_new_node            init"
  "t2   add_new_node_with_audit add_new_node_with_audit init"
  "t3   add_new_node            upsert_w7               init"
  "t4   add_new_node_active     upsert_w7_active        init"
  "t5   add_new_node            delete_by_uuid          zero"
)

OUT="./results-cloud-${PREFIX}"
mkdir -p "$OUT"
SUMMARY="$OUT/SUMMARY.txt"
{ echo "# single-client matrix '${PREFIX}' started $(date -u +%FT%TZ)"
  echo "# host=$FALKOR_HOST tls=${FALKOR_TLS:-no} client=$CLIENT"; echo; } > "$SUMMARY"

START_TS=$(date +%s)

for tier in "${TIERS[@]}"; do
  read -r tier_name init_size <<<"$tier"
  for test in "${TESTS[@]}"; do
    read -r tname shape workload kind <<<"$test"

    case "$kind" in
      init) start_id=$init_size ;;
      zero) start_id=0 ;;
    esac

    tag="${tname}_${tier_name}"
    graph="${PREFIX}_${tag}"
    tier_dir="$OUT/$tag"
    mkdir -p "$tier_dir"

    {
      echo
      echo "########## ${tag}  (shape=$shape workload=$workload init=$init_size start=$start_id) ##########"
      echo "graph=$graph"
      echo
    } | tee -a "$SUMMARY"

    echo "[init] ${tag}..."
    if ! $SSH "$CLIENT" "$REMOTE_ENV cd ~/benchmark-python && source .venv/bin/activate && \
        python -u -m bench2.cli init --host \$FALKOR_HOST --port \$FALKOR_PORT $TLS_FLAG \
          --username \$FALKOR_USER --password \$FALKOR_PASS \
          --graph $graph --shape $shape --nodes $init_size --batch-size 1000" \
        2>&1 | tee "$tier_dir/init.log"; then
      echo "[matrix] FAIL init $tag" | tee -a "$SUMMARY"
      continue
    fi

    echo "[run] ${tag}..."
    if ! $SSH "$CLIENT" "$REMOTE_ENV cd ~/benchmark-python && source .venv/bin/activate && \
        python -u -m bench2.cli run --host \$FALKOR_HOST --port \$FALKOR_PORT $TLS_FLAG \
          --username \$FALKOR_USER --password \$FALKOR_PASS \
          --graph $graph --workload $workload --name ${workload}_${tag} \
          --start-id $start_id --ops $OPS --batch-size 1000 --warmup-batches 10" \
        2>&1 | tee "$tier_dir/run.log"; then
      echo "[matrix] FAIL run $tag" | tee -a "$SUMMARY"
      continue
    fi

    grep -E "^\[run\] " "$tier_dir/run.log" | tee -a "$SUMMARY" || true
    echo "[matrix] OK $tag" | tee -a "$SUMMARY"

    echo "[cleanup] drop graph $graph"
    PY_TLS="${FALKOR_TLS:+True}"; PY_TLS="${PY_TLS:-False}"
    $SSH "$CLIENT" "$REMOTE_ENV cd ~/benchmark-python && source .venv/bin/activate && \
      python -u -c \"
from benchmark.falkor_client import BenchmarkClient
import os
c = BenchmarkClient(host=os.environ['FALKOR_HOST'], port=int(os.environ['FALKOR_PORT']),
                    graph_name='$graph', username=os.environ['FALKOR_USER'],
                    password=os.environ['FALKOR_PASS'], tls=$PY_TLS)
try: c.graph.delete()
except Exception as e: print('drop failed:', e)
print('graph $graph dropped')
\"" 2>&1 | tail -3 || true
  done
done

END_TS=$(date +%s)
{ echo
  echo "# single-client matrix '${PREFIX}' done in $(( (END_TS-START_TS)/60 )) min"; } | tee -a "$SUMMARY"
