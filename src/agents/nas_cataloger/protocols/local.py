"""
Local filesystem protocol adapter.
Optimised for Windows (NTFS) and Linux/macOS (ext4/APFS) paths.
Uses os.scandir for fast directory traversal without stat overhead.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

from .base import FileInfo, NASProtocol


class LocalProtocol(NASProtocol):
    """
    Direct local filesystem access.

    Windows optimisations:
    - Uses os.scandir (single syscall per dir, returns DirEntry with cached stat)
    - Skips junction points / reparse points to avoid loops
    - Handles long paths via \\\\?\\ prefix on Windows

    Linux/macOS optimisations:
    - Skips /proc, /sys, /dev pseudo-filesystems automatically
    - Follows symlinks only when explicitly requested
    """

    SKIP_DIRS_LINUX = {"/proc", "/sys", "/dev", "/run"}
    SKIP_SUFFIXES = {".tmp", ".part", ".crdownload"}

    def __init__(self, follow_symlinks: bool = False,
                 skip_hidden: bool = False):
        self.follow_symlinks = follow_symlinks
        self.skip_hidden = skip_hidden
        self._is_windows = os.name == "nt"

    def _normalize(self, path: str) -> str:
        """Apply long-path prefix on Windows."""
        if self._is_windows and len(path) > 255 and not path.startswith("\\\\?\\"):
            return "\\\\?\\" + path.replace("/", "\\")
        return path

    def connect(self) -> None:
        pass  # no-op for local

    def disconnect(self) -> None:
        pass

    def _entry_to_info(self, entry: os.DirEntry) -> FileInfo | None:
        try:
            stat = entry.stat(follow_symlinks=self.follow_symlinks)
            name = entry.name
            if self.skip_hidden and name.startswith("."):
                return None
            if self._is_windows and entry.is_junction():
                return None  # skip junctions to avoid loops
            return FileInfo(
                path=entry.path,
                name=name,
                size_bytes=stat.st_size if entry.is_file(
                    follow_symlinks=self.follow_symlinks) else 0,
                modified=stat.st_mtime,
                is_dir=entry.is_dir(follow_symlinks=self.follow_symlinks),
                suffix=Path(name).suffix.lower(),
                protocol="local",
            )
        except (PermissionError, OSError):
            return None

    def walk(self, path: str, recursive: bool = True) -> Iterator[FileInfo]:
        path = self._normalize(path)
        try:
            with os.scandir(path) as it:
                for entry in it:
                    info = self._entry_to_info(entry)
                    if info is None:
                        continue
                    yield info
                    if recursive and info.is_dir:
                        # skip known pseudo-filesystems on Linux
                        if entry.path in self.SKIP_DIRS_LINUX:
                            continue
                        yield from self.walk(entry.path, recursive=True)
        except (PermissionError, OSError):
            return

    def list_dir(self, path: str) -> list[FileInfo]:
        return [i for i in self.walk(path, recursive=False) if i is not None]

    def read_bytes(self, path: str, max_bytes: int = 65536) -> bytes:
        path = self._normalize(path)
        with open(path, "rb") as f:
            return f.read(max_bytes)

    def read_bytes_at(self, path: str, offset: int, length: int) -> bytes:
        """Efficient seek-based read for local files."""
        path = self._normalize(path)
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    def move(self, src: str, dst: str) -> None:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)

    def delete(self, path: str) -> None:
        p = Path(path)
        if p.is_dir():
            raise ValueError("Will not delete directories")
        p.unlink()

    def mkdir(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
