"""
Archon Indexing Pipeline — Resumable, Incremental, Parallel
────────────────────────────────────────────────────────────
Designed for local-only operation:
  - All LLM calls → Ollama (local GPU)
  - All face detection → InsightFace (local GPU)
  - All API calls → free public REST APIs
  - Graph storage → Neo4j (local Docker) or Kuzu

Key features:
  - Resumable: SQLite state tracker — restart from checkpoint on interruption
  - Incremental: skips unchanged files (SHA-256 + mtime comparison)
  - Parallel: bounded worker pool (separate limits for I/O vs LLM vs face)
  - Progress: real-time stats via callback or SSE
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from src.graph.base import GraphBackend, NodeData, RelData
from src.graph.schema import NodeType, RelType
from src.graph.factory import get_backend
from src.enrichers.metadata import extract_all, categorize
from src.agents.nas_cataloger.protocols.factory import protocol_factory
from src.pipeline.state import IndexState
from src.pipeline.worker import IndexWorkerPool, WorkItem


class ArchonIndexer:
    """
    Main indexing pipeline.

    Args:
        backend:        GraphBackend instance (or None to auto-detect from env)
        state_label:    Label for SQLite state DB (allows multiple concurrent indexes)
        enrich_llm:     Run LLM enrichment
        enrich_vision:  Run vision enrichment (LLaVA)
        enrich_faces:   Run face detection and clustering
        enrich_api:     Run external API enrichment (EOL, CVE)
        dry_run:        Extract and enrich but don't write to graph
        io_workers:     Parallel file I/O threads (default 8)
        llm_workers:    Parallel Ollama calls (default 2, GPU bound)
        face_workers:   Parallel face detection calls (default 1, GPU bound)
        on_progress:    Optional callback(WorkResult)
        incremental:    Skip unchanged files (default True)
    """

    def __init__(
        self,
        backend: GraphBackend | None = None,
        state_label: str = "default",
        enrich_llm: bool = True,
        enrich_vision: bool = True,
        enrich_faces: bool = True,
        enrich_api: bool = True,
        dry_run: bool = False,
        io_workers: int = 8,
        llm_workers: int = 2,
        face_workers: int = 1,
        on_progress: Callable | None = None,
        incremental: bool = True,
    ):
        self.backend       = backend or get_backend()
        self.state_label   = state_label
        self.enrich_llm    = enrich_llm
        self.enrich_vision = enrich_vision
        self.enrich_faces  = enrich_faces
        self.enrich_api    = enrich_api
        self.dry_run       = dry_run
        self.io_workers    = io_workers
        self.llm_workers   = llm_workers
        self.face_workers  = face_workers
        self.on_progress   = on_progress
        self.incremental   = incremental
        self._face_enricher = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def index(self, source: str, recursive: bool = True) -> dict[str, Any]:
        """
        Index all files at source into the graph.
        Resumable — safe to interrupt and restart.
        source: local path, smb://..., nfs://...
        """
        stats: dict[str, Any] = {
            "source": source,
            "files_scanned": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "errors": 0,
            "started_at": time.time(),
        }

        with self.backend, IndexState(self.state_label) as state:
            self.backend.init_schema()
            run_id = state.start_run(source)

            proto, path = protocol_factory(source)

            pool = IndexWorkerPool(
                graph_backend=self.backend,
                state=state,
                io_workers=self.io_workers,
                llm_workers=self.llm_workers,
                face_workers=self.face_workers,
                enrich_llm=self.enrich_llm,
                enrich_vision=self.enrich_vision,
                enrich_faces=self.enrich_faces,
                enrich_api=self.enrich_api,
                on_progress=self.on_progress,
            )

            BATCH_SIZE = 500
            batch: list[WorkItem] = []

            with proto:
                for file_info in proto.walk(path, recursive=recursive):
                    stats["files_scanned"] += 1

                    if file_info.is_dir:
                        if not self.dry_run:
                            self._write_directory(file_info)
                        continue

                    file_id = self._file_id(file_info)
                    category = categorize(file_info.suffix)

                    # Incremental check — skip if unchanged
                    if self.incremental:
                        # Quick mtime check before hashing
                        needs = state.needs_indexing(
                            file_id, sha256="",
                            modified=file_info.modified,
                            stages_needed=IndexState.STAGE_METADATA,
                        )
                        if not needs:
                            stats["files_skipped"] += 1
                            continue

                    state.mark_started(
                        file_id, file_info.path,
                        file_info.host, file_info.share,
                        file_info.size_bytes, file_info.modified,
                    )

                    if not self.dry_run:
                        batch.append(WorkItem(
                            file_id=file_id,
                            path=file_info.path,
                            host=file_info.host,
                            share=file_info.share,
                            size_bytes=file_info.size_bytes,
                            modified=file_info.modified,
                            suffix=file_info.suffix,
                            category=category,
                            protocol_obj=proto,
                        ))

                    if len(batch) >= BATCH_SIZE:
                        batch_stats = pool.process_batch(batch)
                        stats["files_indexed"] += batch_stats["succeeded"]
                        stats["errors"]        += batch_stats["failed"]
                        batch = []

                # Process remaining batch
                if batch and not self.dry_run:
                    batch_stats = pool.process_batch(batch)
                    stats["files_indexed"] += batch_stats["succeeded"]
                    stats["errors"]        += batch_stats["failed"]

            # Final face clustering pass
            if self.enrich_faces and pool._face_enricher:
                face_stats = pool._face_enricher.write_to_graph()
                stats["face_clusters"] = face_stats.get("clusters_created", 0)

            state.end_run(run_id, stats)

        stats["duration_secs"] = round(time.time() - stats["started_at"], 1)
        stats["files_per_second"] = round(
            stats["files_scanned"] / max(stats["duration_secs"], 0.1), 1
        )
        return stats

    def resume(self, source: str) -> dict[str, Any]:
        """
        Resume a previously interrupted index run.
        Only processes files that haven't completed all enrichment stages.
        """
        with IndexState(self.state_label) as state:
            incomplete = state.get_incomplete(
                stages_needed=self._stages_needed(),
                limit=10000,
            )

        if not incomplete:
            return {"status": "already_complete", "files_remaining": 0}

        # Re-index only the incomplete files
        # (Re-open protocol for each file path)
        stats = {
            "files_resumed": len(incomplete),
            "files_completed": 0,
            "errors": 0,
        }

        with self.backend, IndexState(self.state_label) as state:
            pool = IndexWorkerPool(
                graph_backend=self.backend,
                state=state,
                io_workers=self.io_workers,
                llm_workers=self.llm_workers,
                enrich_llm=self.enrich_llm,
                enrich_vision=self.enrich_vision,
                enrich_faces=self.enrich_faces,
                enrich_api=self.enrich_api,
                on_progress=self.on_progress,
            )

            # Group by protocol/host to open connections efficiently
            items = []
            for f in incomplete:
                proto, path = protocol_factory(f["path"])
                category = categorize(Path(f["path"]).suffix.lower())
                items.append(WorkItem(
                    file_id=f["id"],
                    path=f["path"],
                    host=f.get("host", ""),
                    share=f.get("share", ""),
                    size_bytes=0,
                    modified=0,
                    suffix=Path(f["path"]).suffix.lower(),
                    category=category,
                    protocol_obj=proto,
                ))

            batch_stats = pool.process_batch(items)
            stats["files_completed"] = batch_stats["succeeded"]
            stats["errors"] = batch_stats["failed"]

        return stats

    def status(self) -> dict[str, Any]:
        """Get current indexing status from state DB."""
        with IndexState(self.state_label) as state:
            return {
                "state_db": str(state.db_path),
                "index_stats": state.stats(),
                "last_run": state.last_run_stats(),
            }

    def _stages_needed(self) -> int:
        stages = IndexState.STAGE_METADATA
        if self.enrich_llm:    stages |= IndexState.STAGE_LLM
        if self.enrich_vision: stages |= IndexState.STAGE_VISION
        if self.enrich_faces:  stages |= IndexState.STAGE_FACE
        if self.enrich_api:    stages |= IndexState.STAGE_API
        return stages

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _file_id(self, file_info: Any) -> str:
        return hashlib.sha256(
            f"{file_info.host}:{file_info.share}:{file_info.path}".encode()
        ).hexdigest()[:24]

    def _dir_id(self, path: str, host: str, share: str) -> str:
        return hashlib.sha256(f"{host}:{share}:{path}".encode()).hexdigest()[:24]

    def _write_directory(self, dir_info: Any) -> None:
        dir_id = self._dir_id(dir_info.path, dir_info.host, dir_info.share)
        self.backend.upsert_node(NodeData(
            type=NodeType.DIRECTORY, id=dir_id,
            props={
                "path": dir_info.path,
                "name": dir_info.name,
                "host": dir_info.host,
                "share": dir_info.share,
            }
        ))

    # ── LLM enrichment (called by worker) ─────────────────────────────────────

    def _llm_enrich(self, path: str, props: dict) -> tuple[dict, dict]:
        from src.enrichers.llm_enricher import (
            enrich_document, enrich_image_vision, enrich_code, enrich_binary
        )
        category = props.get("file_category", "other")
        llm_props: dict = {}
        entity_data: dict = {}

        if category == "document":
            try:
                import fitz
                doc = fitz.open(path)
                text = "".join(p.get_text() for p in doc)
                doc.close()
            except Exception:
                try:
                    with open(path, "r", errors="replace") as f:
                        text = f.read(10000)
                except Exception:
                    text = ""
            if text.strip():
                result = enrich_document(text, path)
                entity_data = result.pop("_entities", {})
                llm_props.update({k: v for k, v in result.items() if v})

        elif category == "image" and self.enrich_vision:
            result = enrich_image_vision(path)
            entity_data = result.pop("_vision", {})
            llm_props.update({k: v for k, v in result.items() if v})

        elif category == "code":
            try:
                with open(path, "r", errors="replace") as f:
                    content = f.read(5000)
                result = enrich_code(path, content)
                entity_data = result.pop("_code", {})
                llm_props.update({k: v for k, v in result.items() if v})
            except Exception:
                pass

        elif category == "executable":
            result = enrich_binary(path, props)
            entity_data = result.pop("_binary", {})
            llm_props.update({k: v for k, v in result.items() if v})

        return llm_props, entity_data

    def _write_entities(self, file_id: str, entity_data: dict) -> None:
        for topic in entity_data.get("topics", []):
            if not topic: continue
            tid = f"topic_{hashlib.sha256(topic.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.TOPIC, id=tid, props={"name": topic}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.MENTIONS,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=tid, to_type=NodeType.TOPIC,
            ))

        for person in entity_data.get("people", []):
            if not person: continue
            pid = f"person_{hashlib.sha256(person.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.PERSON, id=pid, props={"name": person, "known": False}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.MENTIONS,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=pid, to_type=NodeType.PERSON,
            ))

        for org in entity_data.get("organizations", []):
            if not org: continue
            oid = f"org_{hashlib.sha256(org.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.ORGANIZATION, id=oid, props={"name": org}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.MENTIONS,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=oid, to_type=NodeType.ORGANIZATION,
            ))

        for loc in entity_data.get("locations", []):
            if not loc: continue
            lid = f"loc_{hashlib.sha256(loc.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.LOCATION, id=lid, props={"name": loc}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.LOCATED_AT,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=lid, to_type=NodeType.LOCATION,
            ))

    def _api_enrich(self, props: dict) -> dict[str, Any]:
        result: dict[str, Any] = {}
        category = props.get("file_category")
        if category == "executable":
            name = props.get("product_name", "").lower()
            if name:
                try:
                    import httpx
                    r = httpx.get(
                        f"https://endoflife.date/api/{name}.json", timeout=5
                    )
                    if r.status_code == 200:
                        cycles = r.json()
                        if cycles:
                            latest = cycles[0]
                            result["latest_version"] = latest.get("latest")
                            eol = latest.get("eol")
                            result["eol_status"] = (
                                "eol" if eol is True else
                                "supported" if eol is False else "unknown"
                            )
                except Exception:
                    pass
        return result
