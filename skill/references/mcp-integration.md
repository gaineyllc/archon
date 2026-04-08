# MCP Integration Guide

## Claude Desktop

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "archon": {
      "command": "npx",
      "args": ["archon"],
      "env": {
        "SMB_HOST": "192.168.1.100",
        "SMB_SHARE": "media",
        "SMB_USER": "admin",
        "SMB_PASS": "yourpassword",
        "NAS_DRY_RUN": "true",
        "IPTORRENTS_USER": "youruser",
        "IPTORRENTS_PASS": "yourpass",
        "SYNOLOGY_HOST": "http://192.168.1.100:5000",
        "SYNOLOGY_USER": "admin",
        "SYNOLOGY_PASS": "yourpass"
      }
    }
  }
}
```

Or point directly at the local project:
```json
{
  "mcpServers": {
    "archon": {
      "command": "uv",
      "args": ["--directory", "F:\\projects\\archon", "run", "python", "-m", "src.mcp_server"]
    }
  }
}
```

## Claude Code / Cursor / Windsurf

Add `.mcp.json` to your project root:

```json
{
  "mcpServers": {
    "archon": {
      "command": "npx",
      "args": ["archon"]
    }
  }
}
```

## HTTP/SSE Mode (remote clients)

Start the server in HTTP mode:
```bash
uv run python -m src.mcp_server --http
```
Server runs on `http://0.0.0.0:8765/sse`

Configure MCP client with:
```json
{
  "mcpServers": {
    "archon": {
      "url": "http://your-machine-ip:8765/sse"
    }
  }
}
```

## OpenClaw

Place the `skill/` directory in your OpenClaw skills path, or reference the
`SKILL.md` directly. OpenClaw will auto-discover the skill and invoke it
when the user asks about NAS cataloguing or torrent hunting.

## Available MCP Tools

### NAS Tools
| Tool | Description |
|---|---|
| `nas_list_directory` | List files (local/SMB/NFS) |
| `nas_get_file_info` | File metadata |
| `nas_compute_hash` | SHA-256 hash |
| `nas_read_text` | Read file content |
| `nas_find_duplicates` | Dedup scan |
| `nas_move_file` | Move (cross-protocol) |
| `nas_delete_file` | Delete (dry_run guard) |
| `nas_create_directory` | mkdir -p |
| `nas_catalogue_report` | Full markdown report |
| `nas_list_smb_shares` | Discover SMB shares |
| `nas_protocol_info` | Parse URI metadata |

### Torrent Tools
| Tool | Description |
|---|---|
| `torrent_search` | Search IPTorrents |
| `torrent_get_file` | Fetch .torrent bytes |
| `torrent_add_download` | Add to Download Station |
| `torrent_list_jobs` | List active downloads |
