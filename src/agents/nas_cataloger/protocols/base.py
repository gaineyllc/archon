"""
Abstract base class for NAS protocol adapters.
All protocol implementations must subclass NASProtocol.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterator


@dataclass
class FileInfo:
    """Unified file metadata across all protocols."""
    path: str                    # full path as seen by the protocol
    name: str                    # filename only
    size_bytes: int
    modified: float              # unix timestamp
    is_dir: bool
    suffix: str                  # lowercase extension e.g. ".mp4"
    protocol: str                # "local" | "smb" | "nfs"
    share: str = ""              # SMB share name or NFS export path
    host: str = ""               # remote host if applicable
    sha256: str = ""             # populated on demand
    extra: dict = field(default_factory=dict)  # protocol-specific metadata

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / 1_048_576, 2)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1_073_741_824, 3)


class NASProtocol(ABC):
    """
    Abstract base for protocol-aware NAS access.
    Implementations handle connection lifecycle, optimised directory
    traversal, and file I/O — hiding protocol details from the agent.
    """

    # ── Connection ─────────────────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> None:
        """Establish connection / mount."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection / unmount."""

    def __enter__(self) -> "NASProtocol":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ── Traversal ──────────────────────────────────────────────────────────────

    @abstractmethod
    def walk(self, path: str, recursive: bool = True) -> Iterator[FileInfo]:
        """Yield FileInfo for every entry under path."""

    @abstractmethod
    def list_dir(self, path: str) -> list[FileInfo]:
        """Non-recursive directory listing."""

    # ── File I/O ───────────────────────────────────────────────────────────────

    @abstractmethod
    def read_bytes(self, path: str, max_bytes: int = 65536) -> bytes:
        """Read up to max_bytes from a file."""

    @abstractmethod
    def move(self, src: str, dst: str) -> None:
        """Move/rename a file."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete a file (never a directory)."""

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Create directory (including parents)."""

    # ── Helpers ────────────────────────────────────────────────────────────────

    def compute_hash(self, path: str, chunk_size: int = 65536) -> str:
        """SHA-256 hash using read_bytes in chunks."""
        h = hashlib.sha256()
        offset = 0
        while True:
            chunk = self.read_bytes_at(path, offset, chunk_size)
            if not chunk:
                break
            h.update(chunk)
            offset += len(chunk)
            if len(chunk) < chunk_size:
                break
        return h.hexdigest()

    def read_bytes_at(self, path: str, offset: int, length: int) -> bytes:
        """
        Read `length` bytes starting at `offset`.
        Default: inefficient fallback — subclasses should override for
        seek-capable protocols (local, SMB2+, NFS v3+).
        """
        data = self.read_bytes(path, max_bytes=offset + length)
        return data[offset:offset + length]

    def read_text(self, path: str, max_chars: int = 4000,
                  encoding: str = "utf-8") -> str:
        raw = self.read_bytes(path, max_bytes=max_chars * 4)
        return raw.decode(encoding, errors="replace")[:max_chars]
