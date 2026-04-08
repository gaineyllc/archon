"""
Kuzu graph backend — embedded, no server, Cypher-compatible.
Default backend for local-first deployments.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any

from .base import GraphBackend, NodeData, RelData
from .schema import KUZU_NODE_DDL, KUZU_REL_DDL

try:
    import kuzu
    _KUZU_AVAILABLE = True
except ImportError:
    _KUZU_AVAILABLE = False


class KuzuBackend(GraphBackend):
    """
    Embedded Kuzu graph database.
    Data stored at db_path (default: F:/archon-graph/kuzu).
    No server required.
    """

    def __init__(self, db_path: str | None = None):
        if not _KUZU_AVAILABLE:
            raise RuntimeError("kuzu not installed. Run: uv add kuzu")
        from src.config import kuzu_db_dir
        self.db_path = db_path or os.getenv(
            "KUZU_DB_PATH", str(kuzu_db_dir())
        )
        self._db = None
        self._conn = None

    def connect(self) -> None:
        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(self.db_path)
        self._conn = kuzu.Connection(self._db)

    def close(self) -> None:
        self._conn = None
        self._db = None

    def init_schema(self) -> None:
        for stmt in KUZU_NODE_DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    self._conn.execute(stmt)
                except Exception:
                    pass  # table already exists
        for stmt in KUZU_REL_DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    self._conn.execute(stmt)
                except Exception:
                    pass

    def _props_to_set(self, props: dict, alias: str = "n") -> tuple[str, dict]:
        """Build SET clause and param dict from props."""
        parts = []
        params = {}
        for k, v in props.items():
            if v is None:
                continue
            param_name = f"p_{k}"
            parts.append(f"{alias}.{k} = ${param_name}")
            params[param_name] = v
        return ", ".join(parts), params

    def upsert_node(self, node: NodeData) -> None:
        if not node.props:
            return
        props = {**node.props, "id": node.id}
        # Build MERGE + SET
        set_clause, params = self._props_to_set(props)
        params["node_id"] = node.id
        cypher = f"""
            MERGE (n:{node.type} {{id: $node_id}})
            SET {set_clause}
        """
        self._conn.execute(cypher, params)

    def upsert_nodes(self, nodes: list[NodeData]) -> None:
        for node in nodes:
            self.upsert_node(node)

    def upsert_rel(self, rel: RelData) -> None:
        params = {
            "from_id": rel.from_id,
            "to_id": rel.to_id,
            **{f"r_{k}": v for k, v in rel.props.items() if v is not None},
        }
        prop_set = ""
        if rel.props:
            parts = [f"r.{k} = $r_{k}" for k in rel.props if rel.props[k] is not None]
            if parts:
                prop_set = f"SET {', '.join(parts)}"

        cypher = f"""
            MATCH (a:{rel.from_type} {{id: $from_id}})
            MATCH (b:{rel.to_type} {{id: $to_id}})
            MERGE (a)-[r:{rel.type}]->(b)
            {prop_set}
        """
        self._conn.execute(cypher, params)

    def upsert_rels(self, rels: list[RelData]) -> None:
        for rel in rels:
            self.upsert_rel(rel)

    def query(self, cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
        result = self._conn.execute(cypher, params or {})
        rows = []
        while result.has_next():
            row = result.get_next()
            col_names = result.get_column_names()
            rows.append(dict(zip(col_names, row)))
        return rows

    def node_exists(self, node_type: str, node_id: str) -> bool:
        result = self.query(
            f"MATCH (n:{node_type} {{id: $id}}) RETURN count(n) AS c",
            {"id": node_id}
        )
        return result[0]["c"] > 0 if result else False

    def delete_node(self, node_type: str, node_id: str) -> None:
        self._conn.execute(
            f"MATCH (n:{node_type} {{id: $id}}) DETACH DELETE n",
            {"id": node_id}
        )
