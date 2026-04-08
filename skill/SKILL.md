---
name: onyx-agent
description: >
  Local AI agent platform for NAS file intelligence and torrent management.
  Use when asked to: catalogue, scan, analyse, organise, or deduplicate files
  on a NAS, file share, SMB share, or local directory. Also use when asked to
  search for a movie or TV show on IPTorrents and add it to Synology Download
  Station. Triggers on: "scan my NAS", "find duplicates", "catalogue files",
  "organise my media", "download [show/movie]", "search iptorrents",
  "add to Download Station", "find torrent for", "clean up my file share".
  Requires onyx-agent running locally (uv run python -m src.mcp_server).
---

# onyx-agent Skill

Local GPU-accelerated agents for NAS file intelligence and torrent hunting.
Project root: `F:\projects\onyx-agent`

## Agents

### 1. NAS File Intelligence Agent
Catalogues, deduplicates, and organises files on any source:
- `local`: Windows/Linux/macOS paths
- `smb://user:pass@host/share/subpath` — SMB2/3
- `nfs://host/export/subpath` — NFSv3/4

**Key tools** (all accept `source` URI):
- `nas_list_directory(source, recursive)` — list files
- `nas_find_duplicates(source)` — SHA-256 dedup scan
- `nas_catalogue_report(source, output_path)` — markdown report
- `nas_move_file(source, destination)` — move (cross-protocol OK)
- `nas_delete_file(source)` — delete (dry_run guard)
- `nas_list_smb_shares(host, username, password)` — discover shares

Always run with `NAS_DRY_RUN=true` unless user explicitly confirms writes.
Use `llava` model for image/video content analysis.

### 2. Torrent Hunter Agent
Finds and downloads media via IPTorrents + Synology Download Station.

Quality priority: `Remux > 2160p > 1080p BluRay > 1080p WEB-DL > 720p`
Folder routing: movies → `DS_DOWNLOAD_DIR_MOVIES`, TV → `DS_DOWNLOAD_DIR_TV`

**Key tools:**
- `torrent_search(query, category)` — search IPTorrents
- `torrent_get_file(download_url)` — fetch .torrent bytes
- `torrent_add_download(torrent_b64, destination_folder)` — add to DS
- `torrent_list_jobs()` — list active downloads

Always confirm with the user before calling `torrent_add_download`.

## Running the Agents

```bash
# Start MCP server (stdio — for Claude Desktop/Code)
cd F:\projects\onyx-agent
uv run python -m src.mcp_server

# Start MCP server (HTTP — for web clients)
uv run python -m src.mcp_server --http

# Run the FastAPI server (REST endpoints)
uv run uvicorn src.api.main:app --reload

# Run tests
uv run python -m pytest tests/ -v
```

## Available Local Models (Ollama)

| Model | Use for |
|---|---|
| `qwen2.5-coder:32b` | Code generation, debugging |
| `deepseek-r1:32b` | Hard reasoning, architecture |
| `llava:latest` | Image/video content analysis |
| `llama3.2:latest` | Fast general tasks |

Switch model: set `AGENT_MODEL` or `NAS_AGENT_MODEL` in `.env`.

## Config & Credentials

Copy `.env.example` → `.env` and fill in:
- SMB: `SMB_HOST`, `SMB_SHARE`, `SMB_USER`, `SMB_PASS`
- NFS: `NFS_HOST`, `NFS_EXPORT`
- IPTorrents: `IPTORRENTS_USER`, `IPTORRENTS_PASS`
- Synology: `SYNOLOGY_HOST`, `SYNOLOGY_USER`, `SYNOLOGY_PASS`
- Folders: `DS_DOWNLOAD_DIR_TV`, `DS_DOWNLOAD_DIR_MOVIES`

See `references/protocol-guide.md` for URI format details and examples.
See `references/mcp-integration.md` for Claude Desktop / Claude Code setup.
