"""
Neo4j graph backend — requires a running Neo4j instance.
Use when you want a full graph server with browser UI and APOC plugins.

Connection via env vars:
  NEO4J_URI      e.g. bolt://localhost:7687
  NEO4J_USER     e.g. neo4j
  NEO4J_PASSWORD e.g. yourpassword
"""
from __future__ import annotations
import os
from typing import Any

from .base import GraphBackend, NodeData, RelData

try:
    from neo4j import GraphDatabase
    _NEO4J_AVAILABLE = True
except ImportError:
    _NEO4J_AVAILABLE = False


class Neo4jBackend(GraphBackend):

    def __init__(self, uri: str | None = None, user: str | None = None,
                 password: str | None = None):
        if not _NEO4J_AVAILABLE:
            raise RuntimeError("neo4j not installed. Run: uv add neo4j")
        from src.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        self.uri      = uri      or NEO4J_URI
        self.user     = user     or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self._driver  = None

    def connect(self) -> None:
        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._driver.verify_connectivity()

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None

    def init_schema(self) -> None:
        constraints = [
            ("File",          "id"),
            ("Directory",     "id"),
            ("Person",        "id"),
            ("FaceCluster",   "id"),
            ("Location",      "id"),
            ("Organization",  "id"),
            ("Topic",         "id"),
            ("Tag",           "id"),
            ("Collection",    "id"),
            ("Event",         "id"),
            ("MediaItem",     "id"),
            ("Application",   "id"),
            ("Binary",        "id"),
            ("Vendor",        "id"),
            ("Product",       "id"),
            ("Version",       "id"),
            ("Vulnerability", "id"),
            ("License",       "id"),
            ("Dependency",    "id"),
            ("Certificate",   "id"),
        ]
        with self._driver.session() as s:
            for label, prop in constraints:
                try:
                    s.run(
                        f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                        f"REQUIRE n.{prop} IS UNIQUE"
                    )
                except Exception:
                    pass

    def upsert_node(self, node: NodeData) -> None:
        props = {**node.props, "id": node.id}
        # Remove None values
        props = {k: v for k, v in props.items() if v is not None}
        with self._driver.session() as s:
            s.run(
                f"MERGE (n:{node.type} {{id: $id}}) SET n += $props",
                {"id": node.id, "props": props}
            )

    def upsert_nodes(self, nodes: list[NodeData]) -> None:
        for node in nodes:
            self.upsert_node(node)

    def upsert_rel(self, rel: RelData) -> None:
        props = {k: v for k, v in rel.props.items() if v is not None}
        with self._driver.session() as s:
            s.run(
                f"""
                MATCH (a:{rel.from_type} {{id: $from_id}})
                MATCH (b:{rel.to_type} {{id: $to_id}})
                MERGE (a)-[r:{rel.type}]->(b)
                SET r += $props
                """,
                {"from_id": rel.from_id, "to_id": rel.to_id, "props": props}
            )

    def upsert_rels(self, rels: list[RelData]) -> None:
        for rel in rels:
            self.upsert_rel(rel)

    def query(self, cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
        with self._driver.session() as s:
            result = s.run(cypher, params or {})
            return [dict(record) for record in result]

    def node_exists(self, node_type: str, node_id: str) -> bool:
        rows = self.query(
            f"MATCH (n:{node_type} {{id: $id}}) RETURN count(n) AS c",
            {"id": node_id}
        )
        return rows[0]["c"] > 0 if rows else False

    def delete_node(self, node_type: str, node_id: str) -> None:
        with self._driver.session() as s:
            s.run(
                f"MATCH (n:{node_type} {{id: $id}}) DETACH DELETE n",
                {"id": node_id}
            )
