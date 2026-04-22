"""FalkorDB client wrapper for the benchmark."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class QueryResult:
    """Timing result of a single query execution."""

    duration_ms: float
    success: bool
    error: str | None = None


class BenchmarkClient:
    """Synchronous FalkorDB client wrapper used by the benchmark runner."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        graph_name: str = "benchmark",
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        from falkordb import FalkorDB

        kwargs: dict = {"host": host, "port": port}
        if username:
            kwargs["username"] = username
        if password:
            kwargs["password"] = password
        self._db = FalkorDB(**kwargs)
        self._graph_name = graph_name
        self._graph = self._db.select_graph(graph_name)

    @property
    def graph(self):
        return self._graph

    def execute_query(self, query: str, params: dict | None = None) -> QueryResult:
        """Execute a Cypher query and return timing info."""
        start = time.perf_counter()
        try:
            self._graph.query(query, params=params)
            elapsed = (time.perf_counter() - start) * 1000.0
            return QueryResult(duration_ms=elapsed, success=True)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000.0
            return QueryResult(duration_ms=elapsed, success=False, error=str(exc))

    def graph_size(self) -> tuple[int, int]:
        """Return (node_count, edge_count)."""
        try:
            nodes = self._graph.query("MATCH (n) RETURN count(n)").result_set[0][0]
        except Exception:
            nodes = 0
        try:
            edges = self._graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
        except Exception:
            edges = 0
        return (nodes, edges)

    def delete_graph(self) -> None:
        """Delete the graph completely."""
        try:
            self._graph.delete()
        except Exception:
            pass

    def create_uuid_pair_index(self, label: str = "entity") -> None:
        """Create a composite range index on (uuid_hi, uuid_lo) for the given label."""
        try:
            self._graph.query(
                f"CREATE INDEX FOR (n:{label}) ON (n.uuid_hi, n.uuid_lo)"
            )
        except Exception:
            pass
