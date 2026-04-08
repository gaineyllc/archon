# Onyx Security Agent

A bespoke AI agent built with LangGraph + Ollama for local, GPU-accelerated inference.

## Stack

| Layer | Technology |
|---|---|
| LLM Runtime | [Ollama](https://ollama.ai) (local, GPU) |
| Agent Framework | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| Vector Store | [ChromaDB](https://www.trychroma.com/) |
| API | [FastAPI](https://fastapi.tiangolo.com/) + Pydantic v2 |
| Package Manager | [uv](https://docs.astral.sh/uv/) |

## Quickstart

```bash
# 1. Pull a model
ollama pull llama3.2

# 2. Install dependencies
uv sync

# 3. Copy env
cp .env.example .env

# 4. Run the API
uv run uvicorn src.api.main:app --reload

# 5. Chat
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What time is it?"}'
```

## Project Structure

```
onyx-agent/
├── src/
│   ├── agent/
│   │   ├── graph.py      # LangGraph ReAct agent
│   │   └── memory.py     # ChromaDB persistent memory
│   ├── tools/
│   │   └── registry.py   # Tool definitions
│   └── api/
│       └── main.py       # FastAPI endpoints
├── tests/
│   └── test_tools.py
├── .env.example
└── pyproject.toml
```

## Adding Tools

In `src/tools/registry.py`, decorate any function with `@tool` and add it to `get_tools()`.

## Running Tests

```bash
uv run pytest tests/ -v
```
