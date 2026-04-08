"""
Graph backend factory.
Reads GRAPH_BACKEND env var: "kuzu" (default) or "neo4j".
"""
from __future__ import annotations
import os
from .base import GraphBackend


def get_backend(backend: str | None = None) -> GraphBackend:
    from src.config import GRAPH_BACKEND
    name = (backend or GRAPH_BACKEND).lower()
    if name == "kuzu":
        from .kuzu_backend import KuzuBackend
        return KuzuBackend()
    elif name == "neo4j":
        from .neo4j_backend import Neo4jBackend
        return Neo4jBackend()
    else:
        raise ValueError(f"Unknown graph backend: {name!r}. Use 'kuzu' or 'neo4j'.")
