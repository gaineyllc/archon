"""
Abstract graph backend interface.
Both KuzuBackend and Neo4jBackend implement this.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeData:
    type: str
    id: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelData:
    type: str
    from_id: str
    from_type: str
    to_id: str
    to_type: str
    props: dict[str, Any] = field(default_factory=dict)


class GraphBackend(ABC):

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def init_schema(self) -> None: ...

    @abstractmethod
    def upsert_node(self, node: NodeData) -> None: ...

    @abstractmethod
    def upsert_nodes(self, nodes: list[NodeData]) -> None: ...

    @abstractmethod
    def upsert_rel(self, rel: RelData) -> None: ...

    @abstractmethod
    def upsert_rels(self, rels: list[RelData]) -> None: ...

    @abstractmethod
    def query(self, cypher: str, params: dict | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def node_exists(self, node_type: str, node_id: str) -> bool: ...

    @abstractmethod
    def delete_node(self, node_type: str, node_id: str) -> None: ...

    def __enter__(self) -> "GraphBackend":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()
