"""
Bounded parallel worker queue for the indexing pipeline.
Processes files concurrently without overwhelming Ollama or the graph DB.

Architecture:
  - ThreadPoolExecutor with configurable concurrency
  - Separate concurrency limits for I/O vs LLM enrichment
  - Progress tracking via callback or SSE stream
  - Graceful shutdown on interrupt
"""
from __future__ import annotations

import hashlib
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from src.pipeline.state import IndexState


@dataclass
class WorkItem:
    file_id: str
    path: str
    host: str
    share: str
    size_bytes: int
    modified: float
    suffix: str
    category: str
    protocol_obj: Any   # NASProtocol instance


@dataclass
class WorkResult:
    file_id: str
    path: str
    success: bool
    stages_completed: int
    duration_ms: int
    error: str | None = None


class IndexWorkerPool:
    """
    Parallel file processing pool with:
    - Separate thread pools for I/O and LLM work
    - Rate limiting on LLM calls (max N concurrent)
    - Progress callbacks
    - Graceful cancellation
    """

    def __init__(
        self,
        graph_backend,
        state: IndexState,
        io_workers: int = 8,         # parallel file reads / metadata
        llm_workers: int = 2,        # parallel Ollama calls (GPU bound)
        face_workers: int = 1,       # face detection (GPU bound)
        enrich_llm: bool = True,
        enrich_vision: bool = True,
        enrich_faces: bool = True,
        enrich_api: bool = True,
        on_progress: Callable[[WorkResult], None] | None = None,
    ):
        self.graph        = graph_backend
        self.state        = state
        self.io_workers   = io_workers
        self.llm_workers  = llm_workers
        self.face_workers = face_workers
        self.enrich_llm   = enrich_llm
        self.enrich_vision= enrich_vision
        self.enrich_faces = enrich_faces
        self.enrich_api   = enrich_api
        self.on_progress  = on_progress

        self._cancel       = threading.Event()
        self._llm_sem      = threading.Semaphore(llm_workers)
        self._face_sem     = threading.Semaphore(face_workers)
        self._face_enricher= None

    def cancel(self) -> None:
        self._cancel.set()

    def process_batch(self, items: list[WorkItem]) -> dict[str, Any]:
        """
        Process a batch of files in parallel.
        Returns aggregate stats.
        """
        stats = {
            "processed": 0, "succeeded": 0,
            "failed": 0, "skipped": 0,
        }

        with ThreadPoolExecutor(max_workers=self.io_workers) as pool:
            futures = {
                pool.submit(self._process_one, item): item
                for item in items
                if not self._cancel.is_set()
            }
            for future in as_completed(futures):
                if self._cancel.is_set():
                    break
                result: WorkResult = future.result()
                stats["processed"] += 1
                if result.success:
                    stats["succeeded"] += 1
                else:
                    stats["failed"] += 1
                if self.on_progress:
                    self.on_progress(result)

        return stats

    def _process_one(self, item: WorkItem) -> WorkResult:
        start = time.monotonic()
        try:
            stages = self._do_process(item)
            return WorkResult(
                file_id=item.file_id,
                path=item.path,
                success=True,
                stages_completed=stages,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            self.state.mark_error(item.file_id, str(e))
            return WorkResult(
                file_id=item.file_id,
                path=item.path,
                success=False,
                stages_completed=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
            )

    def _do_process(self, item: WorkItem) -> int:
        from src.graph.base import NodeData, RelData
        from src.graph.schema import NodeType, RelType
        from src.enrichers.metadata import extract_all

        stages = 0

        # ── Stage 1: Metadata extraction ──────────────────────────────────────
        props = extract_all(item.path)
        props.update({
            "path": item.path, "name": item.path.split("\\")[-1].split("/")[-1],
            "extension": item.suffix, "size_bytes": item.size_bytes,
            "modified": item.modified, "protocol": "local",
            "host": item.host, "share": item.share,
            "indexed_at": time.time(), "enrichment_status": "partial",
        })

        # Hash
        try:
            sha256 = item.protocol_obj.compute_hash(item.path)
            props["sha256"] = sha256
        except Exception:
            sha256 = None

        # Write to graph
        self.graph.upsert_node(NodeData(
            type=NodeType.FILE, id=item.file_id, props=props
        ))
        stages |= IndexState.STAGE_METADATA
        self.state.mark_stage_complete(item.file_id, IndexState.STAGE_METADATA, sha256)

        # ── Stage 2: LLM enrichment ───────────────────────────────────────────
        if self.enrich_llm and item.category in (
            "document", "code", "executable", "web_data"
        ):
            if not self._cancel.is_set():
                with self._llm_sem:
                    try:
                        llm_props, entity_data = self._llm_enrich(item.path, props)
                        if llm_props:
                            self.graph.upsert_node(NodeData(
                                type=NodeType.FILE, id=item.file_id, props=llm_props
                            ))
                            self._write_entities(item.file_id, entity_data)
                        stages |= IndexState.STAGE_LLM
                        self.state.mark_stage_complete(item.file_id, IndexState.STAGE_LLM)
                    except Exception:
                        pass

        # ── Stage 3: Vision enrichment ────────────────────────────────────────
        if self.enrich_vision and item.category == "image":
            if not self._cancel.is_set():
                with self._llm_sem:
                    try:
                        from src.enrichers.llm_enricher import enrich_image_vision
                        result = enrich_image_vision(item.path)
                        result.pop("_vision", None)
                        if result:
                            self.graph.upsert_node(NodeData(
                                type=NodeType.FILE, id=item.file_id, props=result
                            ))
                        stages |= IndexState.STAGE_VISION
                        self.state.mark_stage_complete(item.file_id, IndexState.STAGE_VISION)
                    except Exception:
                        pass

        # ── Stage 4: Face detection ───────────────────────────────────────────
        if self.enrich_faces and item.category in ("image", "video"):
            if not self._cancel.is_set():
                with self._face_sem:
                    try:
                        enricher = self._get_face_enricher()
                        if item.category == "image":
                            enricher.process_image(item.path, item.file_id)
                        else:
                            enricher.process_video(item.path, item.file_id)
                        stages |= IndexState.STAGE_FACE
                        self.state.mark_stage_complete(item.file_id, IndexState.STAGE_FACE)
                    except Exception:
                        pass

        # ── Stage 5: API enrichment ───────────────────────────────────────────
        if self.enrich_api and item.category == "executable":
            if not self._cancel.is_set():
                try:
                    from src.pipeline.indexer import ArchonIndexer
                    api_props = ArchonIndexer._api_enrich(None, props)
                    if api_props:
                        self.graph.upsert_node(NodeData(
                            type=NodeType.FILE, id=item.file_id, props=api_props
                        ))
                    stages |= IndexState.STAGE_API
                    self.state.mark_stage_complete(item.file_id, IndexState.STAGE_API)
                except Exception:
                    pass

        return stages

    def _llm_enrich(self, path: str, props: dict) -> tuple[dict, dict]:
        from src.pipeline.indexer import ArchonIndexer
        dummy = ArchonIndexer.__new__(ArchonIndexer)
        return dummy._llm_enrich(path, props)

    def _write_entities(self, file_id: str, entity_data: dict) -> None:
        from src.pipeline.indexer import ArchonIndexer
        dummy = ArchonIndexer.__new__(ArchonIndexer)
        dummy.backend = self.graph
        dummy._write_entities(file_id, entity_data)

    def _get_face_enricher(self):
        if self._face_enricher is None:
            from src.enrichers.face import FaceEnricher
            self._face_enricher = FaceEnricher(backend=self.graph)
        return self._face_enricher
