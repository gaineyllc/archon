"""Basic smoke tests for the tool registry."""
from src.tools.registry import get_tools, get_current_time


def test_tools_are_registered():
    tools = get_tools()
    assert len(tools) >= 1
    names = [t.name for t in tools]
    assert "get_current_time" in names


def test_get_current_time_returns_iso():
    result = get_current_time.invoke({})
    assert "T" in result  # ISO 8601 contains T separator
