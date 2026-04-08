"""
MCP tools for the Archon knowledge graph.
Natural language + Cypher query interface.
"""
from __future__ import annotations
import os
from typing import Any

from fastmcp import FastMCP
from src.graph.factory import get_backend


def register_graph_tools(mcp: FastMCP) -> None:
    """Register all graph MCP tools on an existing FastMCP instance."""

    def _db():
        b = get_backend()
        b.connect()
        return b

    @mcp.tool
    def graph_query(cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
        """
        Run a raw Cypher query against the Archon knowledge graph.
        Works with both Kuzu (default) and Neo4j backends.

        Example queries:
          MATCH (f:File) WHERE f.file_category = 'video' RETURN f.name, f.duration_secs LIMIT 10
          MATCH (f:File)-[:DEPICTS]->(p:Person) WHERE p.name = 'Neil' RETURN f.path
          MATCH (f:File) WHERE f.contains_secrets = true RETURN f.path, f.secret_types
          MATCH (f:File)-[:HAS_VULNERABILITY]->(v:Vulnerability) WHERE v.cvss_severity = 'critical' RETURN f, v
        """
        db = _db()
        try:
            return db.query(cypher, params)
        finally:
            db.close()

    @mcp.tool
    def graph_find_files(
        category: str | None = None,
        extension: str | None = None,
        min_size_mb: float | None = None,
        max_size_mb: float | None = None,
        contains_person: str | None = None,
        contains_topic: str | None = None,
        has_face: bool | None = None,
        has_secrets: bool | None = None,
        eol_status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search files in the knowledge graph by any combination of attributes.
        All parameters are optional — combine freely.

        Examples:
          graph_find_files(category="video", contains_person="Neil")
          graph_find_files(has_secrets=True)
          graph_find_files(eol_status="eol", category="executable")
          graph_find_files(has_face=True, min_size_mb=1.0)
        """
        conditions = []
        params: dict[str, Any] = {}
        match_clauses = ["MATCH (f:File)"]

        if contains_person:
            match_clauses.append(
                "MATCH (f)-[:MENTIONS|DEPICTS]->(p:Person)"
            )
            conditions.append("toLower(p.name) CONTAINS toLower($person)")
            params["person"] = contains_person

        if contains_topic:
            match_clauses.append("MATCH (f)-[:MENTIONS]->(t:Topic)")
            conditions.append("toLower(t.name) CONTAINS toLower($topic)")
            params["topic"] = contains_topic

        if has_face:
            match_clauses.append("MATCH (f)-[:CONTAINS_FACE]->(fc:FaceCluster)")

        if category:
            conditions.append("f.file_category = $category")
            params["category"] = category
        if extension:
            conditions.append("f.extension = $extension")
            params["extension"] = extension.lower()
        if min_size_mb is not None:
            conditions.append("f.size_bytes >= $min_bytes")
            params["min_bytes"] = int(min_size_mb * 1_048_576)
        if max_size_mb is not None:
            conditions.append("f.size_bytes <= $max_bytes")
            params["max_bytes"] = int(max_size_mb * 1_048_576)
        if has_secrets is not None:
            conditions.append(f"f.contains_secrets = {str(has_secrets).lower()}")
        if eol_status:
            conditions.append("f.eol_status = $eol_status")
            params["eol_status"] = eol_status

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cypher = f"""
            {chr(10).join(match_clauses)}
            {where}
            RETURN DISTINCT f.path AS path, f.name AS name,
                   f.file_category AS category, f.size_bytes AS size_bytes,
                   f.summary AS summary, f.sha256 AS sha256
            LIMIT {limit}
        """
        db = _db()
        try:
            return db.query(cypher, params)
        finally:
            db.close()

    @mcp.tool
    def graph_find_duplicates(
        min_size_mb: float = 0.1,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Find all duplicate files in the graph (matched by SHA-256).
        Returns groups of files with the same content hash.
        """
        cypher = f"""
            MATCH (f:File)
            WHERE f.sha256 IS NOT NULL
              AND f.size_bytes >= {int(min_size_mb * 1_048_576)}
            WITH f.sha256 AS hash, collect(f.path) AS paths,
                 collect(f.size_bytes) AS sizes, count(f) AS cnt
            WHERE cnt > 1
            RETURN hash, paths, sizes[0] AS size_bytes, cnt AS duplicate_count
            ORDER BY size_bytes DESC
            LIMIT {limit}
        """
        db = _db()
        try:
            return db.query(cypher)
        finally:
            db.close()

    @mcp.tool
    def graph_find_by_person(person_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Find all files that depict or mention a specific person.
        Works across photos (face detection), videos, and documents.
        """
        cypher = """
            MATCH (f:File)-[:DEPICTS|MENTIONS|CONTAINS_FACE]->(x)
            WHERE (x:Person AND toLower(x.name) CONTAINS toLower($name))
               OR (x:FaceCluster AND toLower(x.label) CONTAINS toLower($name))
            RETURN DISTINCT f.path AS path, f.name AS name,
                   f.file_category AS category, labels(x)[0] AS matched_via
            ORDER BY f.file_category
            LIMIT $limit
        """
        db = _db()
        try:
            return db.query(cypher, {"name": person_name, "limit": limit})
        finally:
            db.close()

    @mcp.tool
    def graph_face_clusters(labeled_only: bool = False) -> list[dict[str, Any]]:
        """
        List all face clusters detected across photos and videos.
        labeled_only: only return clusters that have been assigned a person name.
        """
        where = "WHERE fc.label <> 'Unknown' OR NOT fc.label STARTS WITH 'Unknown'" if labeled_only else ""
        cypher = f"""
            MATCH (fc:FaceCluster)
            {where}
            OPTIONAL MATCH (fc)-[:SAME_PERSON_AS]->(p:Person)
            RETURN fc.id AS cluster_id, fc.label AS label,
                   fc.face_count AS face_count,
                   p.name AS person_name
            ORDER BY fc.face_count DESC
        """
        db = _db()
        try:
            return db.query(cypher)
        finally:
            db.close()

    @mcp.tool
    def graph_label_face_cluster(cluster_id: str, person_name: str) -> dict[str, str]:
        """
        Assign a name to a face cluster.
        After labeling, graph_find_by_person(person_name) will find all their media.
        """
        from src.enrichers.face import FaceEnricher
        db = _db()
        try:
            enricher = FaceEnricher(backend=db)
            enricher.label_cluster(cluster_id, person_name)
            return {"status": "labeled", "cluster_id": cluster_id,
                    "person_name": person_name}
        finally:
            db.close()

    @mcp.tool
    def graph_security_report() -> dict[str, Any]:
        """
        Generate a security-focused summary of the knowledge graph:
        EOL software, critical CVEs, expired certs, secrets in files, PII.
        """
        db = _db()
        try:
            eol_apps = db.query(
                "MATCH (f:File) WHERE f.eol_status = 'eol' "
                "RETURN f.name, f.file_version, f.company_name LIMIT 20"
            )
            secrets = db.query(
                "MATCH (f:File) WHERE f.contains_secrets = true "
                "RETURN f.path, f.secret_types LIMIT 20"
            )
            pii = db.query(
                "MATCH (f:File) WHERE f.pii_detected = true "
                "RETURN f.path, f.pii_types, f.sensitivity_level LIMIT 20"
            )
            expired_certs = db.query(
                "MATCH (f:File) WHERE f.file_category = 'certificate' "
                "AND f.cert_is_expired = true RETURN f.path, f.cert_subject, f.cert_valid_to"
            )
            expiring_soon = db.query(
                "MATCH (f:File) WHERE f.file_category = 'certificate' "
                "AND f.days_until_expiry > 0 AND f.days_until_expiry < 90 "
                "RETURN f.path, f.cert_subject, f.days_until_expiry ORDER BY f.days_until_expiry"
            )
            unsigned = db.query(
                "MATCH (f:File) WHERE f.file_category = 'executable' "
                "AND f.signed = false RETURN f.path, f.company_name LIMIT 20"
            )
            return {
                "eol_executables":          eol_apps,
                "files_with_secrets":       secrets,
                "files_with_pii":           pii,
                "expired_certificates":     expired_certs,
                "certificates_expiring_soon": expiring_soon,
                "unsigned_executables":     unsigned,
            }
        finally:
            db.close()

    @mcp.tool
    def graph_stats() -> dict[str, Any]:
        """Get high-level statistics about the knowledge graph."""
        db = _db()
        try:
            counts = {}
            for node_type in [
                "File", "Directory", "Person", "FaceCluster",
                "Location", "Organization", "Topic", "Application",
                "Vendor", "Vulnerability", "Certificate"
            ]:
                try:
                    r = db.query(f"MATCH (n:{node_type}) RETURN count(n) AS c")
                    counts[node_type] = r[0]["c"] if r else 0
                except Exception:
                    counts[node_type] = 0

            # File breakdown by category
            try:
                cat_r = db.query(
                    "MATCH (f:File) RETURN f.file_category AS cat, "
                    "count(f) AS cnt ORDER BY cnt DESC"
                )
                counts["by_category"] = {r["cat"]: r["cnt"] for r in cat_r}
            except Exception:
                pass

            return counts
        finally:
            db.close()

    @mcp.tool
    def graph_index_source(
        source: str,
        recursive: bool = True,
        enrich_llm: bool = True,
        enrich_vision: bool = True,
        enrich_faces: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Start indexing a source (local path, SMB, or NFS) into the knowledge graph.
        All enrichment uses local Ollama models — no cloud API calls.

        source: local path, smb://user:pass@host/share/path, nfs://host/export
        dry_run: scan and extract but don't write to graph
        """
        from src.pipeline.indexer import ArchonIndexer
        indexer = ArchonIndexer(
            enrich_llm=enrich_llm,
            enrich_vision=enrich_vision,
            enrich_faces=enrich_faces,
            dry_run=dry_run,
        )
        return indexer.index(source, recursive=recursive)
