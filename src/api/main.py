"""
FastAPI entrypoint — exposes all agents over HTTP.

Endpoints:
  POST /chat                  — base ReAct agent
  POST /agents/nas/catalogue  — NAS file cataloguer
  POST /agents/nas/dedup      — NAS duplicate finder
  POST /agents/torrent/search — IPTorrents search
  POST /agents/torrent/add    — Add torrent to Download Station
  GET  /health
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from src.agent.graph import build_agent
from src.agents.nas_cataloger.graph import build_nas_agent
from src.agents.torrent_hunter.graph import build_torrent_agent

app = FastAPI(title="Onyx Security Agent Platform", version="0.2.0")

# ── Agents ─────────────────────────────────────────────────────────────────────
_base_agent = build_agent()
_nas_agent = build_nas_agent(dry_run=True)      # safe default: dry_run on
_torrent_agent = build_torrent_agent()


# ── Models ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str = "llama3.2"

class ChatResponse(BaseModel):
    reply: str

class NASRequest(BaseModel):
    nas_root: str
    dry_run: bool = True
    message: str = "Catalogue all files, find duplicates, and propose an organisation plan."

class TorrentRequest(BaseModel):
    query: str
    media_type: str = "movie"   # "movie" or "tv"
    auto_confirm: bool = False


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "agents": ["base", "nas_cataloger", "torrent_hunter"]}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = _base_agent.invoke({"messages": [HumanMessage(content=req.message)]})
        return ChatResponse(reply=result["messages"][-1].content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/agents/nas/run", response_model=ChatResponse)
async def nas_run(req: NASRequest) -> ChatResponse:
    try:
        result = _nas_agent.invoke({
            "messages": [HumanMessage(content=req.message)],
            "nas_root": req.nas_root,
            "dry_run": req.dry_run,
        })
        return ChatResponse(reply=result["messages"][-1].content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/agents/torrent/hunt", response_model=ChatResponse)
async def torrent_hunt(req: TorrentRequest) -> ChatResponse:
    try:
        result = _torrent_agent.invoke({
            "messages": [HumanMessage(
                content=f"Find the best torrent for: {req.query} (type: {req.media_type})"
            )],
            "query": req.query,
            "media_type": req.media_type,
            "auto_confirm": req.auto_confirm,
        })
        return ChatResponse(reply=result["messages"][-1].content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
