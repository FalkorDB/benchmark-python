#!/usr/bin/env bash
# Full multi-client matrix: 5 tests x 3 tiers, run from CLIENT_A + CLIENT_B.
# Sequential at the test/tier level; parallel within each (the bench step).
#
# Required env (same as run_multi_client.sh):
#   FALKOR_HOST, FALKOR_PORT, FALKOR_USER, FALKOR_PASS
#   CLIENT_A, CLIENT_B, SSH_KEY

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="bash $HERE/run_multi_client.sh"
OPS=25000

# tier_name init_size
TIERS=(
  "500k 500000"
  "1m   1000000"
  "1_5m 1500000"
)

# test_name shape workload start_a_offset start_b_offset
# (offsets are added to init_size; for delete they are absolute)
TESTS=(
  "t1   add_new_node          add_new_node            init init+ops"
  "t2   add_new_node_with_audit add_new_node_with_audit init init+ops"
  "t3   add_new_node          upsert_w7               init init+ops"
  "t4   add_new_node_active   upsert_w7_active        init init+ops"
  "t5   add_new_node          delete_by_uuid          0    ops"
)

START_TS=$(date +%s)
SUMMARY=./results-cloud-multi/SUMMARY.txt
mkdir -p ./results-cloud-multi
{ echo "# multi-client matrix run started $(date -u +%FT%TZ)"; echo; } > "$SUMMARY"

for tier in "${TIERS[@]}"; do
  read -r tier_name init_size <<<"$tier"
  for test in "${TESTS[@]}"; do
    read -r tname shape workload off_a off_b <<<"$test"

    case "$off_a" in
      init) start_a=$init_size ;;
      0)    start_a=0 ;;
    esac
    case "$off_b" in
      init+ops) start_b=$((init_size + OPS)) ;;
      ops)      start_b=$OPS ;;
    esac

    tag="${tname}_${tier_name}"
    echo
    echo "########## ${tag}  (shape=$shape workload=$workload init=$init_size) ##########"
    echo
    if $RUN "$tag" "$shape" "$workload" "$init_size" "$OPS" "$start_a" "$start_b" \
        2>&1 | tee -a "$SUMMARY"; then
      echo "[matrix] OK $tag" | tee -a "$SUMMARY"
    else
      echo "[matrix] FAIL $tag" | tee -a "$SUMMARY"
    fi
  done
done

END_TS=$(date +%s)
echo | tee -a "$SUMMARY"
echo "# multi-client matrix done in $(( (END_TS-START_TS)/60 )) min" | tee -a "$SUMMARY"
