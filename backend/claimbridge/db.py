"""FalkorDB connection helpers.

Every process (and every thread that writes) opens its own connection.
Agents share nothing but the graph.
"""
import time
from typing import Any

from falkordb import FalkorDB

from claimbridge import config


def connect(graph: str | None = None):
    db = FalkorDB(host=config.FALKORDB_HOST, port=config.FALKORDB_PORT)
    return db.select_graph(graph or config.GRAPH)


def rows(result) -> list[dict[str, Any]]:
    """Turn a FalkorDB result set into a list of dicts keyed by column name."""
    if not result.result_set:
        return []
    names = [h[1] if isinstance(h, (list, tuple)) else h for h in result.header]
    names = [n.decode() if isinstance(n, bytes) else n for n in names]
    return [dict(zip(names, r)) for r in result.result_set]


def run(g, query: str, params: dict | None = None) -> list[dict[str, Any]]:
    params = dict(params or {})
    # Fencing token: a worker's `me` is a tools.Owner carrying the lease generation it was
    # given. Queries that fence on the lease read it as $gen (None for a plain agent id).
    params.setdefault("gen", getattr(params.get("me"), "gen", None))
    return rows(g.query(query, params))


def one(g, query: str, params: dict | None = None) -> dict[str, Any] | None:
    r = run(g, query, params)
    return r[0] if r else None


def now_ms() -> int:
    return int(time.time() * 1000)


def drop(graph: str):
    g = connect(graph)
    try:
        g.delete()
    except Exception:
        pass  # graph did not exist
