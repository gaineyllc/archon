"""
Face Recognition Enricher
──────────────────────────
Uses InsightFace (CUDA-accelerated) to:
  1. Detect faces in images and video frames
  2. Generate 512-dim embeddings for each face
  3. Cluster embeddings into FaceCluster nodes (DBSCAN)
  4. Relate files to clusters via CONTAINS_FACE edges
  5. Allow labeling clusters as named Person nodes

All processing is 100% local — no cloud API calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

try:
    import insightface
    from insightface.app import FaceAnalysis
    _INSIGHTFACE_AVAILABLE = True
except ImportError:
    _INSIGHTFACE_AVAILABLE = False

try:
    from sklearn.cluster import DBSCAN
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

from src.graph.base import GraphBackend, NodeData, RelData
from src.graph.schema import NodeType, RelType

# Image extensions to process
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".tiff", ".tif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".ts", ".m2ts"}

# Frame sampling for video (every N seconds)
VIDEO_FRAME_INTERVAL = 30


class FaceEnricher:
    """
    GPU-accelerated face detection, embedding, and clustering.

    Args:
        backend:        Graph backend to write to
        gpu_id:         CUDA device id (-1 = CPU)
        cluster_eps:    DBSCAN epsilon for face clustering (lower = stricter)
        cluster_min:    DBSCAN min_samples
        model_name:     InsightFace model pack (buffalo_l is best quality)
    """

    def __init__(self, backend: GraphBackend, gpu_id: int = 0,
                 cluster_eps: float = 0.4, cluster_min: int = 2,
                 model_name: str = "buffalo_l"):
        if not _INSIGHTFACE_AVAILABLE:
            raise RuntimeError("insightface not installed. Run: uv add insightface onnxruntime-gpu")
        if not _SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not installed. Run: uv add scikit-learn")

        self.backend      = backend
        self.gpu_id       = gpu_id
        self.cluster_eps  = cluster_eps
        self.cluster_min  = cluster_min
        self.model_name   = model_name
        self._app: FaceAnalysis | None = None
        self._embeddings: dict[str, np.ndarray] = {}   # face_id → embedding
        self._file_faces: dict[str, list[str]] = {}     # file_id → [face_ids]

    def _get_app(self) -> FaceAnalysis:
        if self._app is None:
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if self.gpu_id >= 0 else ["CPUExecutionProvider"]
            )
            self._app = FaceAnalysis(name=self.model_name, providers=providers)
            self._app.prepare(ctx_id=self.gpu_id, det_size=(640, 640))
        return self._app

    # ── Image processing ──────────────────────────────────────────────────────

    def process_image(self, file_path: str, file_id: str) -> list[dict[str, Any]]:
        """
        Detect and embed all faces in an image.
        Returns list of face dicts with embedding and bounding box.
        """
        import cv2
        app = self._get_app()
        img = cv2.imread(file_path)
        if img is None:
            return []
        faces = app.get(img)
        result = []
        for i, face in enumerate(faces):
            embedding = face.normed_embedding  # 512-dim unit vector
            face_id = f"{file_id}_face_{i}"
            self._embeddings[face_id] = embedding
            self._file_faces.setdefault(file_id, []).append(face_id)
            result.append({
                "face_id": face_id,
                "file_id": file_id,
                "confidence": float(face.det_score),
                "bbox": face.bbox.tolist(),
                "embedding": embedding.tolist(),
            })
        return result

    # ── Video processing ──────────────────────────────────────────────────────

    def process_video(self, file_path: str, file_id: str,
                      frame_interval: int = VIDEO_FRAME_INTERVAL) -> list[dict[str, Any]]:
        """
        Sample frames from video, detect faces in each.
        Uses ffmpeg (already installed) to extract frames.
        """
        import cv2
        app = self._get_app()
        results = []

        with tempfile.TemporaryDirectory(prefix="archon_frames_") as tmpdir:
            # Extract one frame every N seconds via ffmpeg
            frame_pattern = os.path.join(tmpdir, "frame_%04d.jpg")
            subprocess.run([
                "ffmpeg", "-i", file_path,
                "-vf", f"fps=1/{frame_interval}",
                "-q:v", "2",
                frame_pattern,
                "-hide_banner", "-loglevel", "error"
            ], check=False)

            frame_files = sorted(Path(tmpdir).glob("frame_*.jpg"))
            seen_embeddings: list[np.ndarray] = []

            for frame_file in frame_files:
                frame_num = int(frame_file.stem.split("_")[1])
                timestamp = frame_num * frame_interval

                img = cv2.imread(str(frame_file))
                if img is None:
                    continue
                faces = app.get(img)

                for i, face in enumerate(faces):
                    embedding = face.normed_embedding
                    # Skip near-duplicate embeddings across frames
                    if any(np.dot(embedding, e) > 0.85 for e in seen_embeddings):
                        continue
                    seen_embeddings.append(embedding)

                    face_id = f"{file_id}_t{timestamp}_f{i}"
                    self._embeddings[face_id] = embedding
                    self._file_faces.setdefault(file_id, []).append(face_id)
                    results.append({
                        "face_id": face_id,
                        "file_id": file_id,
                        "confidence": float(face.det_score),
                        "timestamp_secs": timestamp,
                        "embedding": embedding.tolist(),
                    })

        return results

    # ── Batch processing ──────────────────────────────────────────────────────

    def process_directory(self, source_path: str,
                          recursive: bool = True) -> dict[str, Any]:
        """
        Walk a directory and process all image/video files for faces.
        """
        from src.agents.nas_cataloger.protocols.factory import protocol_factory

        proto, path = protocol_factory(source_path)
        stats = {"images_processed": 0, "videos_processed": 0,
                 "faces_found": 0, "errors": 0}

        with proto:
            for info in proto.walk(path, recursive=recursive):
                if info.is_dir:
                    continue
                ext = info.suffix.lower()
                file_id = hashlib.sha256(info.path.encode()).hexdigest()[:16]

                try:
                    if ext in IMAGE_EXTENSIONS:
                        faces = self.process_image(info.path, file_id)
                        stats["images_processed"] += 1
                        stats["faces_found"] += len(faces)
                    elif ext in VIDEO_EXTENSIONS:
                        faces = self.process_video(info.path, file_id)
                        stats["videos_processed"] += 1
                        stats["faces_found"] += len(faces)
                except Exception as e:
                    stats["errors"] += 1
                    stats.setdefault("error_list", []).append(
                        {"path": info.path, "error": str(e)}
                    )

        return stats

    # ── Clustering ────────────────────────────────────────────────────────────

    def cluster_faces(self) -> dict[str, str]:
        """
        Run DBSCAN on all collected embeddings.
        Returns mapping: face_id → cluster_id
        """
        if not self._embeddings:
            return {}

        face_ids = list(self._embeddings.keys())
        matrix = np.stack([self._embeddings[fid] for fid in face_ids])

        # Cosine distance = 1 - cosine similarity (embeddings are unit vectors)
        # Use euclidean on unit vectors ≈ cosine
        clustering = DBSCAN(
            eps=self.cluster_eps,
            min_samples=self.cluster_min,
            metric="euclidean",
            n_jobs=-1,
        ).fit(matrix)

        face_to_cluster: dict[str, str] = {}
        for face_id, label in zip(face_ids, clustering.labels_):
            cluster_id = f"cluster_{label}" if label >= 0 else f"noise_{face_id}"
            face_to_cluster[face_id] = cluster_id

        return face_to_cluster

    # ── Graph writing ─────────────────────────────────────────────────────────

    def write_to_graph(self) -> dict[str, Any]:
        """
        Cluster all detected faces and write FaceCluster nodes +
        CONTAINS_FACE relationships to the graph.
        """
        face_to_cluster = self.cluster_faces()

        # Build cluster → face_ids map
        cluster_faces: dict[str, list[str]] = {}
        for face_id, cluster_id in face_to_cluster.items():
            cluster_faces.setdefault(cluster_id, []).append(face_id)

        # Write FaceCluster nodes
        cluster_nodes = []
        for cluster_id, face_ids in cluster_faces.items():
            if cluster_id.startswith("noise_"):
                continue
            # Representative embedding = mean of cluster
            embeddings = np.stack([self._embeddings[fid] for fid in face_ids])
            rep = embeddings.mean(axis=0)
            rep = rep / np.linalg.norm(rep)

            cluster_nodes.append(NodeData(
                type=NodeType.FACE_CLUSTER,
                id=cluster_id,
                props={
                    "label": f"Unknown ({cluster_id})",
                    "face_count": len(face_ids),
                    "representative_embedding": json.dumps(rep.tolist()),
                }
            ))
        self.backend.upsert_nodes(cluster_nodes)

        # Write CONTAINS_FACE relationships
        rels = []
        for file_id, face_ids in self._file_faces.items():
            for face_id in face_ids:
                cluster_id = face_to_cluster.get(face_id)
                if not cluster_id or cluster_id.startswith("noise_"):
                    continue
                # Extract confidence from face_id metadata
                rels.append(RelData(
                    type=RelType.CONTAINS_FACE,
                    from_id=file_id,
                    from_type=NodeType.FILE,
                    to_id=cluster_id,
                    to_type=NodeType.FACE_CLUSTER,
                    props={"confidence": 1.0},
                ))
        self.backend.upsert_rels(rels)

        return {
            "clusters_created": len(cluster_nodes),
            "relationships_created": len(rels),
            "noise_faces": sum(
                1 for c in face_to_cluster.values() if c.startswith("noise_")
            ),
        }

    def label_cluster(self, cluster_id: str, person_name: str) -> None:
        """
        Label a FaceCluster as a named Person.
        Creates a Person node and SAME_PERSON_AS relationship.
        """
        person_id = f"person_{hashlib.md5(person_name.encode()).hexdigest()[:8]}"
        self.backend.upsert_node(NodeData(
            type=NodeType.PERSON,
            id=person_id,
            props={"name": person_name, "known": True}
        ))
        self.backend.upsert_rel(RelData(
            type=RelType.SAME_PERSON_AS,
            from_id=cluster_id,
            from_type=NodeType.FACE_CLUSTER,
            to_id=person_id,
            to_type=NodeType.PERSON,
            props={"confidence": 1.0}
        ))
        # Also update cluster label
        self.backend.upsert_node(NodeData(
            type=NodeType.FACE_CLUSTER,
            id=cluster_id,
            props={"label": person_name}
        ))

    def find_matching_clusters(self, reference_image_path: str,
                               threshold: float = 0.5) -> list[dict]:
        """
        Given a reference photo, find all FaceCluster nodes that match.
        Use this to find all photos/videos containing a specific person
        without providing their name.
        """
        import cv2
        app = self._get_app()
        img = cv2.imread(reference_image_path)
        if img is None:
            return []

        faces = app.get(img)
        if not faces:
            return []

        ref_embedding = faces[0].normed_embedding
        matches = []

        for cluster_id, face_ids in {
            fid: self._embeddings[fid] for fid in self._embeddings
        }.items():
            # Compare ref against all stored embeddings
            for face_id, emb in self._embeddings.items():
                sim = float(np.dot(ref_embedding, emb))
                if sim >= (1.0 - threshold):
                    matches.append({
                        "face_id": face_id,
                        "cluster_id": cluster_id,
                        "similarity": sim,
                    })

        return sorted(matches, key=lambda x: -x["similarity"])
