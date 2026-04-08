"""
IPTorrents + Synology Download Station Agent
---------------------------------------------
Given a show/movie query, this agent:
  1. Logs into IPTorrents (session-based, credentials from env)
  2. Searches and ranks results (quality, seeders, size)
  3. Picks the best torrent
  4. Adds it to the correct Synology Download Station folder via API

Graph nodes:
  search → rank → confirm → download
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from src.agents.torrent_hunter.tools.iptorrents import get_tools

SYSTEM_PROMPT = """You are a media acquisition assistant.
Given a search query, you find the best quality torrent on IPTorrents
and add it to Synology Download Station in the correct folder.

Quality priority: Remux > 2160p (4K) > 1080p BluRay > 1080p WEB-DL > 720p
Always prefer the torrent with the most seeders at the desired quality tier.
Movies go to /downloads/movies, TV shows go to /downloads/tv.
Ask for confirmation before adding a download job."""


class TorrentHunterState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    query: str           # e.g. "The Brutalist 2024 2160p"
    media_type: str      # "movie" or "tv"
    auto_confirm: bool   # skip confirmation prompt if True


def build_torrent_agent(model: str = "llama3.2") -> object:
    """Build the torrent hunter LangGraph agent."""
    tools = get_tools()
    llm = ChatOllama(model=model, temperature=0).bind_tools(tools)
    tool_node = ToolNode(tools)

    def call_model(state: TorrentHunterState) -> dict:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
        return {"messages": [llm.invoke(messages)]}

    def should_continue(state: TorrentHunterState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    g = StateGraph(TorrentHunterState)
    g.add_node("agent", call_model)
    g.add_node("tools", tool_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue)
    g.add_edge("tools", "agent")
    return g.compile()
