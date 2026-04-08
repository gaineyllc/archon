"""
Tool registry — add custom tools here.
Each tool is a LangChain @tool-decorated function.
"""
from langchain_core.tools import tool


@tool
def search_knowledge_base(query: str) -> str:
    """Search the internal knowledge base for relevant information."""
    # TODO: wire to ChromaDB retriever
    return f"[knowledge_base] No results yet for: {query}"


@tool
def get_current_time() -> str:
    """Return the current UTC time."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def get_tools() -> list:
    """Return the list of tools available to the agent."""
    return [search_knowledge_base, get_current_time]
