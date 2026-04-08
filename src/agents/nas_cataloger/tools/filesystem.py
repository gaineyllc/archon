"""
NAS filesystem tools — safe wrappers the agent can call.
All destructive operations check dry_run before executing.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# Module-level flag set by build_nas_agent
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
    ]


@tool
def list_directory(path: str, recursive: bool = False) -> list[dict[str, Any]]:
    """List files in a directory. Set recursive=True to walk subdirectories."""
    root = Path(path)
    if not root.exists():
        return [{"error": f"Path does not exist: {path}"}]

    walker = root.rglob("*") if recursive else root.iterdir()
    results = []
    for p in walker:
        try:
            stat = p.stat()
            results.append({
                "path": str(p),
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size_bytes": stat.st_size if p.is_file() else None,
                "modified": stat.st_mtime,
                "suffix": p.suffix.lower(),
            })
        except (PermissionError, OSError):
            results.append({"path": str(p), "error": "permission_denied"})
    return results


@tool
def get_file_info(path: str) -> dict[str, Any]:
    """Get detailed metadata for a single file."""
    p = Path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    stat = p.stat()
    return {
        "path": str(p),
        "name": p.name,
        "suffix": p.suffix.lower(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1_048_576, 2),
        "modified": stat.st_mtime,
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
    }


@tool
def compute_file_hash(path: str) -> dict[str, str]:
    """Compute SHA-256 hash of a file for duplicate detection."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return {"path": path, "sha256": h.hexdigest()}
    except (OSError, PermissionError) as e:
        return {"path": path, "error": str(e)}


@tool
def read_text_file(path: str, max_chars: int = 4000) -> dict[str, str]:
    """Read text content from a file (txt, md, json, csv, etc.)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        return {"path": path, "content": content, "truncated": len(content) == max_chars}
    except (OSError, PermissionError) as e:
        return {"path": path, "error": str(e)}


@tool
def find_duplicates(directory: str) -> list[dict[str, Any]]:
    """Scan a directory recursively, group files by SHA-256 hash, return duplicate groups."""
    from collections import defaultdict
    hashes: dict[str, list[str]] = defaultdict(list)
    for root, _, files in os.walk(directory):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                h = hashlib.sha256()
                with open(fpath, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                hashes[h.hexdigest()].append(fpath)
            except (OSError, PermissionError):
                pass
    return [
        {"sha256": h, "count": len(paths), "paths": paths}
        for h, paths in hashes.items()
        if len(paths) > 1
    ]


@tool
def move_file(source: str, destination: str) -> dict[str, str]:
    """Move a file from source to destination. Respects dry_run mode."""
    if _DRY_RUN:
        return {"status": "dry_run", "would_move": source, "to": destination}
    try:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        return {"status": "moved", "from": source, "to": destination}
    except (OSError, shutil.Error) as e:
        return {"status": "error", "error": str(e)}


@tool
def delete_file(path: str) -> dict[str, str]:
    """Delete a file. Respects dry_run mode. CANNOT delete directories."""
    if _DRY_RUN:
        return {"status": "dry_run", "would_delete": path}
    p = Path(path)
    if p.is_dir():
        return {"status": "error", "error": "Will not delete directories via this tool"}
    try:
        p.unlink()
        return {"status": "deleted", "path": path}
    except (OSError, PermissionError) as e:
        return {"status": "error", "error": str(e)}


@tool
def create_directory(path: str) -> dict[str, str]:
    """Create a directory (including parents). Respects dry_run mode."""
    if _DRY_RUN:
        return {"status": "dry_run", "would_create": path}
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return {"status": "created", "path": path}
    except (OSError, PermissionError) as e:
        return {"status": "error", "error": str(e)}


@tool
def generate_catalogue_report(directory: str, output_path: str) -> dict[str, str]:
    """
    Walk a directory and write a markdown catalogue report to output_path.
    Includes file counts, size totals, and extension breakdown.
    """
    from collections import defaultdict
    ext_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "bytes": 0})
    total_files = 0
    total_bytes = 0

    for root, _, files in os.walk(directory):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                size = os.path.getsize(fpath)
                ext = Path(fname).suffix.lower() or "(no ext)"
                ext_stats[ext]["count"] += 1
                ext_stats[ext]["bytes"] += size
                total_files += 1
                total_bytes += size
            except OSError:
                pass

    lines = [
        f"# NAS Catalogue Report\n",
        f"**Root:** `{directory}`\n",
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
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        return {"status": "written", "path": output_path}
    return {"status": "dry_run", "report_preview": report[:500]}
