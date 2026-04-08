"""
NAS filesystem tools — protocol-aware wrappers the agent can call.

Supports local paths, SMB shares (smb://user:pass@host/share/path),
and NFS exports (nfs://host/export/path).

All destructive operations check dry_run before executing.
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.nas_cataloger.protocols.factory import protocol_factory
from src.agents.nas_cataloger.protocols.local import LocalProtocol
from src.agents.nas_cataloger.protocols.base import FileInfo

# Module-level flag — set by get_tools()
_DRY_RUN = True


def get_tools(dry_run: bool = True) -> list:
    global _DRY_RUN
    _DRY_RUN = dry_run
    return [
        list_directory,
        get_file_info,
        compute_file_hash,
        read_text_file,
        find_duplicates,
        move_file,
        delete_file,
        create_directory,
        generate_catalogue_report,
        list_smb_shares,
        get_protocol_info,
    ]


def _fileinfo_to_dict(f: FileInfo) -> dict:
    return {
        "path": f.path, "name": f.name, "type": "dir" if f.is_dir else "file",
        "size_bytes": f.size_bytes, "size_mb": f.size_mb,
        "modified": f.modified, "suffix": f.suffix,
        "protocol": f.protocol, "host": f.host, "share": f.share,
    }


@tool
def get_protocol_info(source: str) -> dict[str, Any]:
    """
    Parse a source URI and return protocol metadata without connecting.
    source: local path, smb://user:pass@host/share/path, or nfs://host/export/path
    """
    try:
        proto, path = protocol_factory(source)
        return {
            "protocol": proto.__class__.__name__,
            "root_path": path,
            "source": source,
            "dry_run": _DRY_RUN,
        }
    except Exception as e:
        return {"error": str(e)}


@tool
def list_smb_shares(host: str, username: str = "", password: str = "",
                    domain: str = "") -> list[dict[str, Any]]:
    """
    List available SMB shares on a remote host.
    Useful for discovery before cataloguing.
    """
    try:
        import smbclient
        smbclient.register_session(
            host,
            username=f"{domain}\\{username}" if domain else username,
            password=password,
        )
        shares = []
        for share in smbclient.listshares(host):
            shares.append({"name": share, "unc": f"\\\\{host}\\{share}"})
        return shares
    except ImportError:
        return [{"error": "smbprotocol not installed. Run: uv add smbprotocol"}]
    except Exception as e:
        return [{"error": str(e)}]


@tool
def list_directory(source: str, recursive: bool = False) -> list[dict[str, Any]]:
    """
    List files in a directory. Supports local paths and UNC/URI sources.
    source: local path, smb://user:pass@host/share/subpath, or nfs://host/export/subpath
    recursive: if True, walk all subdirectories
    """
    try:
        proto, path = protocol_factory(source)
        with proto:
            entries = list(proto.walk(path, recursive=recursive)
                           if recursive else proto.list_dir(path))
        return [_fileinfo_to_dict(f) for f in entries]
    except Exception as e:
        return [{"error": str(e)}]


@tool
def get_file_info(source: str) -> dict[str, Any]:
    """Get detailed metadata for a single file. source is a local path or URI."""
    try:
        proto, path = protocol_factory(source)
        with proto:
            entries = proto.list_dir(str(Path(path).parent))
            target = Path(path).name
            for f in entries:
                if f.name == target:
                    return _fileinfo_to_dict(f)
        return {"error": f"File not found: {path}"}
    except Exception as e:
        return {"error": str(e)}


@tool
def compute_file_hash(source: str) -> dict[str, str]:
    """Compute SHA-256 hash of a file. source is a local path or URI."""
    try:
        proto, path = protocol_factory(source)
        with proto:
            sha256 = proto.compute_hash(path)
        return {"path": source, "sha256": sha256}
    except Exception as e:
        return {"path": source, "error": str(e)}


@tool
def read_text_file(source: str, max_chars: int = 4000) -> dict[str, Any]:
    """Read text content from a file. source is a local path or URI."""
    try:
        proto, path = protocol_factory(source)
        with proto:
            content = proto.read_text(path, max_chars=max_chars)
        return {"path": source, "content": content,
                "truncated": len(content) == max_chars}
    except Exception as e:
        return {"path": source, "error": str(e)}


@tool
def find_duplicates(source: str) -> list[dict[str, Any]]:
    """
    Scan a directory recursively, group files by SHA-256, return duplicate groups.
    source: local path, smb://..., or nfs://...
    """
    hashes: dict[str, list[str]] = defaultdict(list)
    try:
        proto, path = protocol_factory(source)
        with proto:
            for info in proto.walk(path, recursive=True):
                if info.is_dir or info.size_bytes == 0:
                    continue
                try:
                    sha256 = proto.compute_hash(info.path)
                    hashes[sha256].append(info.path)
                except Exception:
                    pass
    except Exception as e:
        return [{"error": str(e)}]

    return [
        {"sha256": h, "count": len(paths), "paths": paths,
         "wasted_bytes": (len(paths) - 1) * _get_size(paths[0])}
        for h, paths in hashes.items()
        if len(paths) > 1
    ]


def _get_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


@tool
def move_file(source: str, destination: str) -> dict[str, str]:
    """
    Move a file. source and destination can be local paths or URIs.
    Cross-protocol moves (SMB → local) are supported via read+write+delete.
    Respects dry_run mode.
    """
    if _DRY_RUN:
        return {"status": "dry_run", "would_move": source, "to": destination}
    try:
        src_proto, src_path = protocol_factory(source)
        dst_proto, dst_path = protocol_factory(destination)

        src_type = type(src_proto).__name__
        dst_type = type(dst_proto).__name__

        if src_type == dst_type:
            # Same protocol — use native move (single round trip)
            with src_proto:
                src_proto.move(src_path, dst_path)
        else:
            # Cross-protocol — read → write → delete
            with src_proto:
                data = src_proto.read_bytes(src_path, max_bytes=10 * 1024 * 1024 * 1024)
            with dst_proto:
                dst_proto.mkdir(str(Path(dst_path).parent))
                dst_proto._write_bytes(dst_path, data)  # type: ignore
            with src_proto:
                src_proto.delete(src_path)

        return {"status": "moved", "from": source, "to": destination}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool
def delete_file(source: str) -> dict[str, str]:
    """Delete a file. Respects dry_run. Will NOT delete directories."""
    if _DRY_RUN:
        return {"status": "dry_run", "would_delete": source}
    try:
        proto, path = protocol_factory(source)
        with proto:
            proto.delete(path)
        return {"status": "deleted", "path": source}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool
def create_directory(source: str) -> dict[str, str]:
    """Create a directory (including parents). Respects dry_run."""
    if _DRY_RUN:
        return {"status": "dry_run", "would_create": source}
    try:
        proto, path = protocol_factory(source)
        with proto:
            proto.mkdir(path)
        return {"status": "created", "path": source}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool
def generate_catalogue_report(source: str, output_path: str) -> dict[str, Any]:
    """
    Walk source recursively and write a markdown catalogue report.
    source: local path, smb://..., or nfs://...
    output_path: local path for the report file
    """
    ext_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "bytes": 0})
    total_files = 0
    total_bytes = 0
    protocol_name = "unknown"

    try:
        proto, path = protocol_factory(source)
        protocol_name = type(proto).__name__
        with proto:
            for info in proto.walk(path, recursive=True):
                if info.is_dir:
                    continue
                ext = info.suffix or "(no ext)"
                ext_stats[ext]["count"] += 1
                ext_stats[ext]["bytes"] += info.size_bytes
                total_files += 1
                total_bytes += info.size_bytes
    except Exception as e:
        return {"error": str(e)}

    lines = [
        f"# NAS Catalogue Report\n\n",
        f"**Source:** `{source}`\n",
        f"**Protocol:** {protocol_name}\n",
        f"**Total files:** {total_files:,}\n",
        f"**Total size:** {total_bytes / 1_073_741_824:.2f} GB\n\n",
        "## By Extension\n\n",
        "| Extension | Count | Size (MB) |\n",
        "|-----------|------:|-----------|\n",
    ]
    for ext, stats in sorted(ext_stats.items(), key=lambda x: -x[1]["bytes"]):
        lines.append(f"| `{ext}` | {stats['count']:,} | {stats['bytes']/1_048_576:.1f} |\n")

    report = "".join(lines)

    if not _DRY_RUN:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        return {"status": "written", "path": output_path,
                "total_files": total_files,
                "total_gb": round(total_bytes / 1_073_741_824, 2)}

    return {"status": "dry_run", "report_preview": report[:800],
            "total_files": total_files,
            "total_gb": round(total_bytes / 1_073_741_824, 2)}
