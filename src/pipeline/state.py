"""
Index state tracker — enables resumable, incremental indexing.

Tracks per-file state in a SQLite database:
  path + host + share → sha256, modified, indexed_at, enrichment_status

On each run:
  - Skip files that haven't changed (same sha256 + modified time)
  - Resume from last checkpoint if interrupted
  - Track which enrichment stages have completed per file
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterator

from src.config import data_dir


def _state_db_path(label: str = "default") -> Path:
    p = data_dir() / "index-state"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{label}.db"


class IndexState:
    """
    SQLite-backed index state store.
    Thread-safe via WAL mode.

    Enrichment stages (bitmask):
      0x01 = metadata extracted
      0x02 = llm enriched
      0x04 = vision enriched
      0x08 = face processed
      0x10 = api enriched
      0xFF = fully complete
    """

    STAGE_METADATA = 0x01
    STAGE_LLM      = 0x02
    STAGE_VISION   = 0x04
    STAGE_FACE     = 0x08
    STAGE_API      = 0x10
    STAGE_COMPLETE = 0xFF

    def __init__(self, label: str = "default"):
        self.db_path = _state_db_path(label)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_state (
                id           TEXT PRIMARY KEY,
                path         TEXT NOT NULL,
                host         TEXT,
                share        TEXT,
                sha256       TEXT,
                size_bytes   INTEGER,
                modified     REAL,
                indexed_at   REAL,
                stages       INTEGER DEFAULT 0,
                error        TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_path ON file_state(path)"
        )
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS run_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at REAL,
                ended_at   REAL,
                source     TEXT,
                files_scanned  INTEGER DEFAULT 0,
                files_indexed  INTEGER DEFAULT 0,
                files_skipped  INTEGER DEFAULT 0,
                errors         INTEGER DEFAULT 0,
                status     TEXT DEFAULT 'running'
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "IndexState":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── File state ─────────────────────────────────────────────────────────────

    def needs_indexing(self, file_id: str, sha256: str,
                       modified: float, stages_needed: int = STAGE_METADATA) -> bool:
        """
        Returns True if the file needs (re-)indexing.
        False if it's already indexed at the same sha256 + modified with all needed stages.
        """
        row = self._conn.execute(
            "SELECT sha256, modified, stages FROM file_state WHERE id = ?",
            (file_id,)
        ).fetchone()

        if row is None:
            return True  # never seen

        stored_sha256, stored_modified, stored_stages = row

        # Content changed
        if sha256 and stored_sha256 != sha256:
            return True

        # Modified time changed (quick check before hashing)
        if abs(stored_modified - modified) > 1.0:
            return True

        # Missing required enrichment stages
        if (stored_stages & stages_needed) != stages_needed:
            return True

        return False

    def mark_started(self, file_id: str, path: str, host: str,
                     share: str, size_bytes: int, modified: float) -> None:
        self._conn.execute("""
            INSERT INTO file_state (id, path, host, share, size_bytes, modified, indexed_at, stages)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(id) DO UPDATE SET
                modified=excluded.modified,
                size_bytes=excluded.size_bytes,
                indexed_at=excluded.indexed_at,
                stages=0, error=NULL
        """, (file_id, path, host, share, size_bytes, modified, time.time()))
        self._conn.commit()

    def mark_stage_complete(self, file_id: str, stage: int,
                            sha256: str | None = None) -> None:
        if sha256:
            self._conn.execute(
                "UPDATE file_state SET stages = stages | ?, sha256 = ? WHERE id = ?",
                (stage, sha256, file_id)
            )
        else:
            self._conn.execute(
                "UPDATE file_state SET stages = stages | ? WHERE id = ?",
                (stage, file_id)
            )
        self._conn.commit()

    def mark_error(self, file_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE file_state SET error = ? WHERE id = ?",
            (error[:500], file_id)
        )
        self._conn.commit()

    def get_incomplete(self, stages_needed: int = STAGE_COMPLETE,
                       limit: int = 1000) -> list[dict]:
        """Return files that haven't completed all required stages."""
        rows = self._conn.execute("""
            SELECT id, path, host, share, stages, error
            FROM file_state
            WHERE (stages & ?) != ?
            AND error IS NULL
            LIMIT ?
        """, (stages_needed, stages_needed, limit)).fetchall()

        return [
            {"id": r[0], "path": r[1], "host": r[2],
             "share": r[3], "stages": r[4], "error": r[5]}
            for r in rows
        ]

    # ── Run log ────────────────────────────────────────────────────────────────

    def start_run(self, source: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO run_log (started_at, source) VALUES (?, ?)",
            (time.time(), source)
        )
        self._conn.commit()
        return cur.lastrowid

    def end_run(self, run_id: int, stats: dict) -> None:
        self._conn.execute("""
            UPDATE run_log SET
                ended_at = ?,
                files_scanned = ?,
                files_indexed = ?,
                files_skipped = ?,
                errors = ?,
                status = 'complete'
            WHERE id = ?
        """, (
            time.time(),
            stats.get("files_scanned", 0),
            stats.get("files_indexed", 0),
            stats.get("files_skipped", 0),
            stats.get("errors", 0),
            run_id,
        ))
        self._conn.commit()

    def last_run_stats(self, source: str | None = None) -> dict | None:
        query = "SELECT * FROM run_log WHERE status = 'complete'"
        params: list = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY ended_at DESC LIMIT 1"
        row = self._conn.execute(query, params).fetchone()
        if not row:
            return None
        cols = ["id","started_at","ended_at","source",
                "files_scanned","files_indexed","files_skipped","errors","status"]
        return dict(zip(cols, row))

    def stats(self) -> dict:
        total    = self._conn.execute("SELECT count(*) FROM file_state").fetchone()[0]
        complete = self._conn.execute(
            "SELECT count(*) FROM file_state WHERE stages = 255"
        ).fetchone()[0]
        errors   = self._conn.execute(
            "SELECT count(*) FROM file_state WHERE error IS NOT NULL"
        ).fetchone()[0]
        pending  = self._conn.execute(
            "SELECT count(*) FROM file_state WHERE stages = 0"
        ).fetchone()[0]
        return {
            "total": total,
            "complete": complete,
            "pending": pending,
            "errors": errors,
            "in_progress": total - complete - errors - pending,
        }
