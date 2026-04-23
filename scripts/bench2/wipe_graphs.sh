#!/usr/bin/env bash
# Delete ALL graphs on the configured FalkorDB instance.
#
# Reads connection from env (FALKOR_HOST / FALKOR_PORT / FALKOR_USER /
# FALKOR_PASS). Lists every graph via `GRAPH.LIST` and runs `GRAPH.DELETE`
# on each one. Prints what it does. Asks for confirmation before deleting
# unless --yes is passed.
#
# Usage:
#   ./scripts/bench2/wipe_graphs.sh           # interactive confirm
#   ./scripts/bench2/wipe_graphs.sh --yes     # no prompt
set -euo pipefail

HOST="${FALKOR_HOST:?FALKOR_HOST not set}"
PORT="${FALKOR_PORT:-6379}"
USER="${FALKOR_USER:-falkordb}"
PASS="${FALKOR_PASS:?FALKOR_PASS not set}"

CONFIRM=1
if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
    CONFIRM=0
fi

# GRAPH.LIST returns a flat array of names. Strip redis-cli quoting.
mapfile -t GRAPHS < <(
    redis-cli -h "$HOST" -p "$PORT" --user "$USER" --pass "$PASS" \
        --no-raw GRAPH.LIST 2>/dev/null \
        | sed -E 's/^[[:space:]]*[0-9]+\)[[:space:]]+"(.*)"$/\1/' \
        | grep -v '^$'
)

if [[ ${#GRAPHS[@]} -eq 0 ]]; then
    echo "No graphs found on $HOST:$PORT."
    exit 0
fi

echo "Found ${#GRAPHS[@]} graph(s) on $HOST:$PORT:"
for g in "${GRAPHS[@]}"; do
    echo "  - $g"
done

if [[ $CONFIRM -eq 1 ]]; then
    read -r -p "Delete ALL of the above? Type YES to confirm: " ans
    if [[ "$ans" != "YES" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

for g in "${GRAPHS[@]}"; do
    echo -n "Deleting $g ... "
    redis-cli -h "$HOST" -p "$PORT" --user "$USER" --pass "$PASS" \
        GRAPH.DELETE "$g" >/dev/null && echo "OK" || echo "FAIL"
done

echo "Done."
