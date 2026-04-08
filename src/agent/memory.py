"""
Persistent agent memory backed by ChromaDB (local vector store).
"""
from pathlib import Path

import chromadb
from chromadb.config import Settings


_DB_PATH = Path(__file__).parent.parent.parent / ".chroma"
_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(_DB_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def get_collection(name: str = "agent_memory") -> chromadb.Collection:
    return get_client().get_or_create_collection(name)


def upsert(doc_id: str, text: str, metadata: dict | None = None) -> None:
    col = get_collection()
    col.upsert(ids=[doc_id], documents=[text], metadatas=[metadata or {}])


def query(text: str, n_results: int = 5) -> list[str]:
    col = get_collection()
    results = col.query(query_texts=[text], n_results=n_results)
    return results["documents"][0] if results["documents"] else []
