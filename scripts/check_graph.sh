#!/usr/bin/env bash
# Quick diagnostic — list graphs and report node/edge counts for the CRM init graph.
set -euo pipefail

HOST="${FALKOR_HOST:-localhost}"
PORT="${FALKOR_PORT:-6379}"
GRAPH="${1:-crm_init_100000}"

echo "=== FalkorDB @ ${HOST}:${PORT} ==="
echo
echo "--- All graphs (GRAPH.LIST) ---"
redis-cli -h "$HOST" -p "$PORT" GRAPH.LIST
echo
echo "--- Target graph: ${GRAPH} ---"
echo "Nodes:"
redis-cli -h "$HOST" -p "$PORT" --no-raw GRAPH.QUERY "$GRAPH" "MATCH (n) RETURN count(n)"
echo
echo "Edges (any rel type):"
redis-cli -h "$HOST" -p "$PORT" --no-raw GRAPH.QUERY "$GRAPH" "MATCH ()-[r]->() RETURN count(r)"
echo
echo "Edges of type :CONNECTED_TO specifically:"
redis-cli -h "$HOST" -p "$PORT" --no-raw GRAPH.QUERY "$GRAPH" "MATCH ()-[r:CONNECTED_TO]->() RETURN count(r)"
echo
echo "Sample 3 nodes:"
redis-cli -h "$HOST" -p "$PORT" --no-raw GRAPH.QUERY "$GRAPH" "MATCH (n) RETURN labels(n), n.id, n.uuid_hi, n.uuid_lo LIMIT 3"
echo
echo "Sample 3 edges:"
redis-cli -h "$HOST" -p "$PORT" --no-raw GRAPH.QUERY "$GRAPH" "MATCH (a)-[r]->(b) RETURN labels(a), type(r), labels(b) LIMIT 3"
echo
echo "Done."
