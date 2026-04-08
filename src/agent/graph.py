"""
Core LangGraph agent definition.
Uses Ollama as the local LLM backend.
"""
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from src.tools.registry import get_tools


# ── State ──────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# ── Graph factory ──────────────────────────────────────────────────────────────

def build_agent(model: str = "llama3.2", system_prompt: str | None = None) -> StateGraph:
    """Build and compile the LangGraph ReAct agent."""

    tools = get_tools()
    llm = ChatOllama(model=model, temperature=0).bind_tools(tools)
    tool_node = ToolNode(tools)

    def call_model(state: AgentState) -> dict:
        messages = state["messages"]
        if system_prompt:
            messages = [SystemMessage(content=system_prompt)] + list(messages)
        response = llm.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph.compile()
