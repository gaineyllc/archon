# onyx-agent

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
git clone https://github.com/gaineyinc/onyx-agent
cd onyx-agent

# 2. Install Python deps
uv sync

# 3. Pull models
ollama pull qwen2.5-coder:32b   # best coding model
ollama pull deepseek-r1:32b     # reasoning
ollama pull llava               # vision (NAS image analysis)

# 4. Configure
cp .env.example .env
# edit .env with your NAS/Synology/IPTorrents credentials

# 5a. Run as MCP server (Claude Desktop / Claude Code / Cursor)
uv run python -m src.mcp_server

# 5b. Run as REST API
uv run uvicorn src.api.main:app --reload

# 5c. Run via npx (after npm install or publish)
npx onyx-agent
```

## MCP Integration

Add to Claude Desktop (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "onyx-agent": {
      "command": "npx",
      "args": ["onyx-agent"],
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
onyx-agent/
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
├── bin/onyx-agent.js              # npm entrypoint
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
