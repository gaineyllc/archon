"""
FastAPI entrypoint — exposes the LangGraph agent over HTTP.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from src.agent.graph import build_agent

app = FastAPI(title="Onyx Security Agent", version="0.1.0")
agent = build_agent()


class ChatRequest(BaseModel):
    message: str
    model: str = "llama3.2"


class ChatResponse(BaseModel):
    reply: str


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = agent.invoke({"messages": [HumanMessage(content=req.message)]})
        last = result["messages"][-1]
        return ChatResponse(reply=last.content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
