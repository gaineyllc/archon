"""
Graph backend factory.
Reads GRAPH_BACKEND env var: "kuzu" (default) or "neo4j".
"""
from __future__ import annotations
import os
from .base import GraphBackend


def get_backend(backend: str | None = None) -> GraphBackend:
    name = (backend or os.getenv("GRAPH_BACKEND", "neo4j")).lower()
    if name == "kuzu":
        from .kuzu_backend import KuzuBackend
        return KuzuBackend()
    elif name == "neo4j":
        from .neo4j_backend import Neo4jBackend
        return Neo4jBackend()
    else:
        raise ValueError(f"Unknown graph backend: {name!r}. Use 'kuzu' or 'neo4j'.")
