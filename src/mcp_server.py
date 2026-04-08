"""
archon MCP Server
─────────────────────
Exposes NAS Cataloguer + Torrent Hunter as MCP tools.
Compatible with Claude Desktop, Claude Code, Cursor, Windsurf,
and any MCP 2024-11-05+ client.

Run:
  uv run python -m src.mcp_server          # stdio (Claude Desktop / Claude Code)
  uv run python -m src.mcp_server --http   # HTTP/SSE on port 8765

Claude Desktop config (~/.claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "archon": {
        "command": "uv",
        "args": ["--directory", "/path/to/archon", "run", "python", "-m", "src.mcp_server"],
        "env": {
          "SMB_HOST": "192.168.1.x",
          "SMB_SHARE": "media",
          "SMB_USER": "user",
          "SMB_PASS": "pass"
        }
      }
    }
  }
"""
from __future__ import annotations

import os
import sys
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    name="archon",
    version="0.2.0",
    description=(
        "Local AI agents powered by Ollama on GPU. "
        "Tools: NAS file cataloguing/dedup/organise (SMB, NFS, local) "
        "and torrent hunting via IPTorrents + Synology Download Station."
    ),
)

# ── NAS Cataloguer tools ───────────────────────────────────────────────────────

from src.agents.nas_cataloger.tools.filesystem import (
    get_tools as _get_nas_tools,
    list_directory as _list_directory,
    get_file_info as _get_file_info,
    compute_file_hash as _compute_file_hash,
    read_text_file as _read_text_file,
    find_duplicates as _find_duplicates,
    move_file as _move_file,
    delete_file as _delete_file,
    create_directory as _create_directory,
    generate_catalogue_report as _generate_catalogue_report,
    list_smb_shares as _list_smb_shares,
    get_protocol_info as _get_protocol_info,
)

_dry_run = os.getenv("NAS_DRY_RUN", "true").lower() == "true"
_get_nas_tools(dry_run=_dry_run)


@mcp.tool
def nas_list_directory(source: str, recursive: bool = False) -> list[dict[str, Any]]:
    """
    List files on a NAS or local directory.
    source: local path, smb://user:pass@host/share/subpath, or nfs://host/export/subpath
    recursive: walk all subdirectories when True
    """
    return _list_directory.invoke({"source": source, "recursive": recursive})


@mcp.tool
def nas_get_file_info(source: str) -> dict[str, Any]:
    """Get metadata for a single file (size, modified, protocol, etc.)."""
    return _get_file_info.invoke({"source": source})


@mcp.tool
def nas_compute_hash(source: str) -> dict[str, str]:
    """Compute SHA-256 hash of a file for duplicate detection."""
    return _compute_file_hash.invoke({"source": source})


@mcp.tool
def nas_read_text(source: str, max_chars: int = 4000) -> dict[str, Any]:
    """Read text content from a file (txt, md, json, csv, code, etc.)."""
    return _read_text_file.invoke({"source": source, "max_chars": max_chars})


@mcp.tool
def nas_find_duplicates(source: str) -> list[dict[str, Any]]:
    """
    Scan a directory recursively and return all duplicate file groups (by SHA-256).
    Includes wasted_bytes per group.
    source: local path, smb://..., or nfs://...
    """
    return _find_duplicates.invoke({"source": source})


@mcp.tool
def nas_move_file(source: str, destination: str) -> dict[str, str]:
    """
    Move a file. Cross-protocol moves supported (e.g. SMB → local).
    Respects NAS_DRY_RUN env var — set to 'false' to execute for real.
    """
    return _move_file.invoke({"source": source, "destination": destination})


@mcp.tool
def nas_delete_file(source: str) -> dict[str, str]:
    """
    Delete a file. Will NOT delete directories.
    Respects NAS_DRY_RUN env var.
    """
    return _delete_file.invoke({"source": source})


@mcp.tool
def nas_create_directory(source: str) -> dict[str, str]:
    """Create a directory (including parents). Respects NAS_DRY_RUN."""
    return _create_directory.invoke({"source": source})


@mcp.tool
def nas_catalogue_report(source: str, output_path: str) -> dict[str, Any]:
    """
    Walk source and generate a markdown catalogue report.
    Returns file counts, total size, and extension breakdown.
    output_path: local path where the .md report will be written.
    """
    return _generate_catalogue_report.invoke(
        {"source": source, "output_path": output_path}
    )


@mcp.tool
def nas_list_smb_shares(host: str, username: str = "",
                        password: str = "", domain: str = "") -> list[dict[str, Any]]:
    """Discover available SMB shares on a remote NAS host."""
    return _list_smb_shares.invoke(
        {"host": host, "username": username, "password": password, "domain": domain}
    )


@mcp.tool
def nas_protocol_info(source: str) -> dict[str, Any]:
    """Parse a source URI and return protocol metadata (without connecting)."""
    return _get_protocol_info.invoke({"source": source})


# ── Torrent Hunter tools ───────────────────────────────────────────────────────

from src.agents.torrent_hunter.tools.iptorrents import (
    search_iptorrents as _search_iptorrents,
    get_torrent_file as _get_torrent_file,
    add_download_job as _add_download_job,
    list_download_jobs as _list_download_jobs,
)


@mcp.tool
def torrent_search(query: str, category: str = "all") -> list[dict[str, Any]]:
    """
    Search IPTorrents for a movie or TV show.
    category: 'movies', 'tv', or 'all'
    Returns results sorted by seeders (best quality first).
    Requires IPTORRENTS_USER + IPTORRENTS_PASS env vars.
    """
    return _search_iptorrents.invoke({"query": query, "category": category})


@mcp.tool
def torrent_get_file(download_url: str) -> dict[str, Any]:
    """
    Download a .torrent file from IPTorrents.
    Returns base64-encoded content for passing to torrent_add_download.
    """
    return _get_torrent_file.invoke({"download_url": download_url})


@mcp.tool
def torrent_add_download(torrent_b64: str, destination_folder: str) -> dict[str, Any]:
    """
    Add a torrent to Synology Download Station.
    torrent_b64: base64 .torrent content from torrent_get_file
    destination_folder: e.g. /volume1/downloads/movies
    Requires SYNOLOGY_HOST + SYNOLOGY_USER + SYNOLOGY_PASS env vars.
    """
    return _add_download_job.invoke(
        {"torrent_b64": torrent_b64, "destination_folder": destination_folder}
    )


@mcp.tool
def torrent_list_jobs() -> list[dict[str, Any]]:
    """List current Synology Download Station tasks with status and progress."""
    return _list_download_jobs.invoke({})


# ── Graph knowledge base tools ────────────────────────────────────────────────
from src.graph.mcp_tools import register_graph_tools
register_graph_tools(mcp)

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="sse", host="0.0.0.0", port=8765)
    else:
        mcp.run(transport="stdio")
