"""
NAS File Intelligence Agent
----------------------------
Uses a local multimodal LLM (via Ollama) to:
  1. Walk NAS directories and fingerprint every file
  2. Run deep content analysis (vision for images/video frames, text extraction for docs)
  3. Build a ChromaDB semantic index of all content
  4. Detect and report duplicates (hash + semantic similarity)
  5. Propose and optionally execute a reorganisation plan
  6. Generate a full catalogue report

Graph nodes:
  scan  → analyse → embed → dedup → plan → execute → report
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from src.agents.nas_cataloger.tools.filesystem import get_tools

SYSTEM_PROMPT = """You are an expert file system analyst.
Your job is to deeply analyse files on a NAS, understand their content,
detect duplicates, and organise everything logically.
Think carefully before moving or deleting anything — always explain your
reasoning and ask for confirmation before destructive operations."""


class CataloguerState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    nas_root: str          # e.g. "\\\\NAS\\media"
    dry_run: bool          # when True, never touch the filesystem


def build_nas_agent(model: str = "llava", dry_run: bool = True) -> object:
    """Build the NAS cataloguer LangGraph agent.

    Uses llava (multimodal) by default so it can visually analyse images
    and video frame thumbnails straight on the RTX 5090.
    """
    tools = get_tools(dry_run=dry_run)
    llm = ChatOllama(model=model, temperature=0).bind_tools(tools)
    tool_node = ToolNode(tools)

    def call_model(state: CataloguerState) -> dict:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
        return {"messages": [llm.invoke(messages)]}

    def should_continue(state: CataloguerState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    g = StateGraph(CataloguerState)
    g.add_node("agent", call_model)
    g.add_node("tools", tool_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue)
    g.add_edge("tools", "agent")
    return g.compile()
