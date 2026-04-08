# archon

Local AI agent platform powered by Ollama (GPU). Three agents, one MCP server.

[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-blue)](https://modelcontextprotocol.io)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-green)](https://python.org)

## Agents

| Agent | What it does |
|---|---|
| **NAS Cataloguer** | Deep-scan file shares (SMB/NFS/local), dedup, organise, report |
| **Torrent Hunter** | Search IPTorrents, pick best quality, add to Synology Download Station |
| **Base Agent** | General ReAct agent via Ollama |

## Stack

| Layer | Technology |
|---|---|
| LLM Runtime | [Ollama](https://ollama.ai) — local, RTX 5090 GPU |
| Agent Framework | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| MCP Server | [FastMCP](https://github.com/prefecthq/fastmcp) v3 |
| SMB Protocol | [smbprotocol](https://github.com/jborean93/smbprotocol) (SMB2/3) |
| Vector Store | [ChromaDB](https://www.trychroma.com/) |
| API | [FastAPI](https://fastapi.tiangolo.com/) + Pydantic v2 |
| Package Manager | [uv](https://docs.astral.sh/uv/) |

## Quickstart

```bash
# 1. Clone
git clone https://github.com/gaineyllc/archon
cd archon

# 2. One-command setup (handles deps, models, Neo4j, .env)
python install.py

# 3. Edit credentials
# Fill in .env with your NAS/Synology/IPTorrents credentials

# 4a. Run as MCP server (Claude Desktop / Claude Code / Cursor)
uv run python -m src.mcp_server

# 4b. Run as REST API
uv run uvicorn src.api.main:app --reload

# 4c. Run via npx
npx archon
```

## Platform Support

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| Local filesystem | ✅ | ✅ | ✅ |
| SMB2/3 | ✅ | ✅ | ✅ |
| NFS | ✅ (NFS Client feature) | ✅ | ✅ |
| GPU (CUDA) | ✅ RTX | ❌ (CPU) | ✅ NVIDIA |
| GPU (Metal) | ❌ | ✅ Ollama only | ❌ |
| PE binary analysis | ✅ | ✅ (lief) | ✅ (lief) |
| ELF binary analysis | ✅ (lief) | ✅ (lief) | ✅ |
| Mach-O binary analysis | ✅ (lief) | ✅ | ✅ (lief) |
| Face recognition | ✅ GPU | ✅ CPU | ✅ GPU |
| Code signing check | PowerShell | codesign | readelf |

Data directory: `~/.archon` (override with `ARCHON_DATA_DIR` env var)

## MCP Integration

Add to Claude Desktop (`~/.claude/claude_desktop_config.json`):

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
        "NAS_DRY_RUN": "true"
      }
    }
  }
}
```

Or for direct project use (`.mcp.json` already included):
```bash
# Claude Code picks this up automatically from .mcp.json
uv run python -m src.mcp_server
```

## Project Structure

```
archon/
├── src/
│   ├── mcp_server.py              # FastMCP server — all tools exposed
│   ├── api/main.py                # FastAPI REST endpoints
│   ├── agent/                     # Base ReAct agent
│   ├── agents/
│   │   ├── nas_cataloguer/
│   │   │   ├── graph.py           # LangGraph agent
│   │   │   ├── protocols/         # SMB / NFS / local adapters
│   │   │   └── tools/filesystem.py
│   │   └── torrent_hunter/
│   │       ├── graph.py
│   │       └── tools/iptorrents.py
├── skill/                         # OpenClaw AgentSkill
│   ├── SKILL.md
│   └── references/
├── bin/archon.js              # npm entrypoint
├── .mcp.json                      # MCP server config (auto-discovered)
├── package.json                   # npm package
├── pyproject.toml
└── .env.example
```

## MCP Tools Reference

See [skill/references/mcp-integration.md](skill/references/mcp-integration.md)

## Protocol Support

See [skill/references/protocol-guide.md](skill/references/protocol-guide.md)

## Running Tests

```bash
uv run python -m pytest tests/ -v
```

## License

MIT
