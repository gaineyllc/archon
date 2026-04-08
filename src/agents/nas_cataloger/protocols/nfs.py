"""
NFS protocol adapter.

Strategy: mount the NFS export to a local temp directory, then delegate
all I/O to LocalProtocol. This avoids reimplementing NFS wire protocol
and gives us all local optimisations (os.scandir, seek, etc.) for free.

Supports:
  - NFSv3 and NFSv4 (via OS mount)
  - Linux: uses `mount -t nfs`
  - Windows: uses `mount` (NFS Client feature must be enabled)
  - macOS: uses `mount_nfs`

OS-specific optimisations applied at mount time:
  Linux:   noatime,nodiratime,rsize=1048576,wsize=1048576,hard,intr
  Windows: anon (read-only mounts), mtype=soft
  macOS:   resvport,rsize=1048576,wsize=1048576,noatime

For read-only cataloguing (dry_run=True), mounts as read-only.
"""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from .base import FileInfo, NASProtocol
from .local import LocalProtocol


class NFSProtocol(NASProtocol):
    """
    NFS protocol adapter via OS-level mount.

    Args:
        host:       NFS server hostname or IP
        export:     Export path on the server (e.g. "/volume1/media")
        version:    NFS version: 3 or 4 (default 3)
        readonly:   Mount read-only (default True — safe for cataloguing)
        mount_opts: Additional mount options (appended to defaults)
    """

    _OS = platform.system()  # "Linux", "Windows", "Darwin"

    def __init__(self, host: str, export: str, version: int = 3,
                 readonly: bool = True, mount_opts: str = ""):
        self.host = host
        self.export = export
        self.version = version
        self.readonly = readonly
        self.extra_opts = mount_opts
        self._mountpoint: str | None = None
        self._local: LocalProtocol | None = None
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    # ── Mount helpers ──────────────────────────────────────────────────────────

    def _build_mount_cmd(self, mountpoint: str) -> list[str]:
        src = f"{self.host}:{self.export}"
        base_opts = self._base_opts()
        if self.extra_opts:
            base_opts += f",{self.extra_opts}"

        if self._OS == "Linux":
            cmd = ["mount", "-t", f"nfs{'' if self.version == 3 else str(self.version)}",
                   "-o", base_opts, src, mountpoint]
        elif self._OS == "Darwin":
            cmd = ["mount_nfs", "-o", base_opts, src, mountpoint]
        elif self._OS == "Windows":
            # Windows NFS client: mount \\host\export Z:
            # We use a temp drive letter approach via `mount`
            cmd = ["mount", f"\\\\{self.host}{self.export.replace('/', '\\')}", mountpoint]
        else:
            raise RuntimeError(f"Unsupported OS for NFS mount: {self._OS}")
        return cmd

    def _base_opts(self) -> str:
        ro = "ro" if self.readonly else "rw"
        if self._OS == "Linux":
            return f"{ro},noatime,nodiratime,rsize=1048576,wsize=1048576,nfsvers={self.version},hard,intr"
        elif self._OS == "Darwin":
            return f"{ro},resvport,rsize=1048576,wsize=1048576,noatime,nfsvers={self.version}"
        elif self._OS == "Windows":
            return f"mtype={'hard' if not self.readonly else 'soft'},anon"
        return ro

    def connect(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="nfs_mount_")
        self._mountpoint = self._tmpdir.name
        cmd = self._build_mount_cmd(self._mountpoint)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self._tmpdir.cleanup()
            raise RuntimeError(
                f"NFS mount failed: {result.stderr.strip()}\n"
                f"Command: {' '.join(cmd)}\n"
                f"Tip: ensure NFS client is installed and you have network access to {self.host}"
            )
        self._local = LocalProtocol()

    def disconnect(self) -> None:
        if self._mountpoint:
            if self._OS == "Windows":
                subprocess.run(["umount", self._mountpoint],
                               capture_output=True)
            else:
                subprocess.run(["umount", self._mountpoint],
                               capture_output=True)
        if self._tmpdir:
            self._tmpdir.cleanup()
        self._mountpoint = None
        self._local = None

    def _abs(self, path: str) -> str:
        """Resolve a share-relative path to an absolute local path."""
        if self._mountpoint is None:
            raise RuntimeError("NFSProtocol not connected. Use with-statement.")
        if Path(path).is_absolute():
            return path
        return str(Path(self._mountpoint) / path.lstrip("/\\"))

    # ── Delegate to LocalProtocol ──────────────────────────────────────────────

    def walk(self, path: str, recursive: bool = True) -> Iterator[FileInfo]:
        for info in self._local.walk(self._abs(path), recursive=recursive):
            # Rewrite protocol metadata
            info.protocol = "nfs"
            info.host = self.host
            info.share = self.export
            yield info

    def list_dir(self, path: str) -> list[FileInfo]:
        return list(self.walk(path, recursive=False))

    def read_bytes(self, path: str, max_bytes: int = 65536) -> bytes:
        return self._local.read_bytes(self._abs(path), max_bytes)

    def read_bytes_at(self, path: str, offset: int, length: int) -> bytes:
        return self._local.read_bytes_at(self._abs(path), offset, length)

    def move(self, src: str, dst: str) -> None:
        if self.readonly:
            raise PermissionError("NFS share mounted read-only. Set readonly=False to enable writes.")
        self._local.move(self._abs(src), self._abs(dst))

    def delete(self, path: str) -> None:
        if self.readonly:
            raise PermissionError("NFS share mounted read-only.")
        self._local.delete(self._abs(path))

    def mkdir(self, path: str) -> None:
        if self.readonly:
            raise PermissionError("NFS share mounted read-only.")
        self._local.mkdir(self._abs(path))


def nfs_from_env() -> NFSProtocol:
    """
    Construct NFSProtocol from environment variables:
      NFS_HOST, NFS_EXPORT, NFS_VERSION (optional, default 3),
      NFS_READONLY (optional, default true)
    """
    return NFSProtocol(
        host=os.environ["NFS_HOST"],
        export=os.environ["NFS_EXPORT"],
        version=int(os.getenv("NFS_VERSION", "3")),
        readonly=os.getenv("NFS_READONLY", "true").lower() == "true",
    )
