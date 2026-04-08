"""
Archon Indexing Pipeline
────────────────────────
Orchestrates: scan → extract → enrich → write graph

Designed for local-only operation:
  - All LLM calls → Ollama (local GPU)
  - All face detection → InsightFace (local GPU)
  - All API calls → free public REST APIs (EOL, NVD, TMDB, MusicBrainz)
  - Graph storage → Kuzu (local) or Neo4j (local server)
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Callable

from src.graph.base import GraphBackend, NodeData, RelData
from src.graph.schema import NodeType, RelType
from src.graph.factory import get_backend
from src.extractors.metadata_extract import extract_all, categorize
from src.agents.nas_cataloger.protocols.factory import protocol_factory


class ArchonIndexer:
    """
    Main indexing pipeline.

    Args:
        backend:        GraphBackend instance (or None to auto-detect from env)
        enrich_llm:     Run LLM enrichment (summary, entities, topics)
        enrich_vision:  Run vision enrichment (LLaVA for images/video)
        enrich_faces:   Run face detection and clustering
        enrich_api:     Run external API enrichment (EOL, CVE, TMDB)
        dry_run:        Extract and enrich but don't write to graph
        on_progress:    Optional callback(file_path, status, props)
    """

    def __init__(
        self,
        backend: GraphBackend | None = None,
        enrich_llm: bool = True,
        enrich_vision: bool = True,
        enrich_faces: bool = True,
        enrich_api: bool = True,
        dry_run: bool = False,
        on_progress: Callable | None = None,
    ):
        self.backend       = backend or get_backend()
        self.enrich_llm    = enrich_llm
        self.enrich_vision = enrich_vision
        self.enrich_faces  = enrich_faces
        self.enrich_api    = enrich_api
        self.dry_run       = dry_run
        self.on_progress   = on_progress
        self._face_enricher = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def index(self, source: str, recursive: bool = True) -> dict[str, Any]:
        """
        Index all files at source into the graph.
        source: local path, smb://..., nfs://...
        """
        stats = {
            "files_scanned": 0,
            "files_indexed": 0,
            "files_enriched": 0,
            "errors": 0,
            "started_at": time.time(),
        }

        with self.backend:
            self.backend.init_schema()
            proto, path = protocol_factory(source)

            with proto:
                for file_info in proto.walk(path, recursive=recursive):
                    stats["files_scanned"] += 1
                    try:
                        result = self._process_file(file_info, proto)
                        if result.get("indexed"):
                            stats["files_indexed"] += 1
                        if result.get("enriched"):
                            stats["files_enriched"] += 1
                    except Exception as e:
                        stats["errors"] += 1
                        stats.setdefault("error_list", []).append(
                            {"path": file_info.path, "error": str(e)}
                        )

            # Final face clustering pass
            if self.enrich_faces and self._face_enricher:
                face_stats = self._face_enricher.write_to_graph()
                stats["face_clusters"] = face_stats.get("clusters_created", 0)

        stats["duration_secs"] = round(time.time() - stats["started_at"], 1)
        return stats

    # ── File processing ────────────────────────────────────────────────────────

    def _process_file(self, file_info: Any, proto: Any) -> dict[str, bool]:
        result = {"indexed": False, "enriched": False}

        if file_info.is_dir:
            self._write_directory(file_info)
            return result

        # Generate stable ID
        file_id = hashlib.sha256(
            f"{file_info.host}:{file_info.share}:{file_info.path}".encode()
        ).hexdigest()[:24]

        # Base props from FileInfo
        props: dict[str, Any] = {
            "path":        file_info.path,
            "name":        file_info.name,
            "extension":   file_info.suffix,
            "size_bytes":  file_info.size_bytes,
            "modified":    file_info.modified,
            "protocol":    file_info.protocol,
            "host":        file_info.host,
            "share":       file_info.share,
            "indexed_at":  time.time(),
            "enrichment_status": "pending",
        }

        # Deep metadata extraction
        try:
            extracted = extract_all(file_info.path)
            props.update(extracted)
        except Exception:
            pass

        # SHA-256 hash
        try:
            props["sha256"] = proto.compute_hash(file_info.path)
        except Exception:
            pass

        # Write base node
        if not self.dry_run:
            self.backend.upsert_node(NodeData(
                type=NodeType.FILE, id=file_id, props=props
            ))
            # CHILD_OF directory
            dir_id = self._dir_id(str(Path(file_info.path).parent),
                                  file_info.host, file_info.share)
            self.backend.upsert_rel(RelData(
                type=RelType.CHILD_OF,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=dir_id,    to_type=NodeType.DIRECTORY,
            ))

        result["indexed"] = True

        # ── LLM enrichment ─────────────────────────────────────────────────
        if self.enrich_llm:
            try:
                llm_props, entity_data = self._llm_enrich(
                    file_info.path, props
                )
                props.update(llm_props)
                props["enrichment_status"] = "complete"
                if not self.dry_run:
                    self.backend.upsert_node(NodeData(
                        type=NodeType.FILE, id=file_id, props=llm_props
                    ))
                    self._write_entities(file_id, entity_data)
                result["enriched"] = True
            except Exception:
                pass

        # ── Face enrichment ────────────────────────────────────────────────
        if self.enrich_faces and props.get("file_category") in ("image", "video"):
            try:
                enricher = self._get_face_enricher()
                if props["file_category"] == "image":
                    enricher.process_image(file_info.path, file_id)
                else:
                    enricher.process_video(file_info.path, file_id)
            except Exception:
                pass

        # ── API enrichment ─────────────────────────────────────────────────
        if self.enrich_api:
            try:
                api_props = self._api_enrich(props)
                if api_props and not self.dry_run:
                    self.backend.upsert_node(NodeData(
                        type=NodeType.FILE, id=file_id, props=api_props
                    ))
            except Exception:
                pass

        if self.on_progress:
            self.on_progress(file_info.path, "indexed", props)

        return result

    # ── LLM enrichment ────────────────────────────────────────────────────────

    def _llm_enrich(self, path: str, props: dict) -> tuple[dict, dict]:
        from src.enrichers.llm_enricher import (
            enrich_document, enrich_image_vision, enrich_code, enrich_binary
        )
        category = props.get("file_category", "other")
        llm_props = {}
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

    # ── Entity graph writing ──────────────────────────────────────────────────

    def _write_entities(self, file_id: str, entity_data: dict) -> None:
        for topic in entity_data.get("topics", []):
            if not topic:
                continue
            topic_id = f"topic_{hashlib.md5(topic.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.TOPIC, id=topic_id, props={"name": topic}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.MENTIONS,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=topic_id,  to_type=NodeType.TOPIC,
            ))

        for person in entity_data.get("people", []):
            if not person:
                continue
            person_id = f"person_{hashlib.md5(person.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.PERSON, id=person_id,
                props={"name": person, "known": False}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.MENTIONS,
                from_id=file_id,  from_type=NodeType.FILE,
                to_id=person_id,  to_type=NodeType.PERSON,
            ))

        for org in entity_data.get("organizations", []):
            if not org:
                continue
            org_id = f"org_{hashlib.md5(org.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.ORGANIZATION, id=org_id, props={"name": org}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.MENTIONS,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=org_id,    to_type=NodeType.ORGANIZATION,
            ))

        for loc in entity_data.get("locations", []):
            if not loc:
                continue
            loc_id = f"loc_{hashlib.md5(loc.encode()).hexdigest()[:8]}"
            self.backend.upsert_node(NodeData(
                type=NodeType.LOCATION, id=loc_id, props={"name": loc}
            ))
            self.backend.upsert_rel(RelData(
                type=RelType.LOCATED_AT,
                from_id=file_id, from_type=NodeType.FILE,
                to_id=loc_id,    to_type=NodeType.LOCATION,
            ))

    # ── API enrichment ────────────────────────────────────────────────────────

    def _api_enrich(self, props: dict) -> dict[str, Any]:
        """Enrich with free REST APIs based on file category."""
        result: dict[str, Any] = {}
        category = props.get("file_category")

        if category == "executable":
            # EOL check via endoflife.date
            name = props.get("product_name", "").lower()
            if name:
                try:
                    import httpx
                    r = httpx.get(
                        f"https://endoflife.date/api/{name}.json",
                        timeout=5
                    )
                    if r.status_code == 200:
                        cycles = r.json()
                        if cycles:
                            latest = cycles[0]
                            result["latest_version"] = latest.get("latest")
                            eol = latest.get("eol")
                            result["eol_status"] = (
                                "eol" if eol is True else
                                "supported" if eol is False else
                                "unknown"
                            )
                except Exception:
                    pass

        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _write_directory(self, dir_info: Any) -> None:
        dir_id = self._dir_id(dir_info.path, dir_info.host, dir_info.share)
        if not self.dry_run:
            self.backend.upsert_node(NodeData(
                type=NodeType.DIRECTORY, id=dir_id,
                props={
                    "path": dir_info.path,
                    "name": dir_info.name,
                    "host": dir_info.host,
                    "share": dir_info.share,
                }
            ))

    def _dir_id(self, path: str, host: str, share: str) -> str:
        return hashlib.sha256(f"{host}:{share}:{path}".encode()).hexdigest()[:24]

    def _get_face_enricher(self):
        if self._face_enricher is None:
            from src.enrichers.face import FaceEnricher
            self._face_enricher = FaceEnricher(backend=self.backend)
        return self._face_enricher
