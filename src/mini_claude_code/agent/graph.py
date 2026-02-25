"""Build the main LangGraph StateGraph for the agent loop.

Graph structure:
    +-----------+
    |   START   |
    +-----+-----+
          |
    +-----v------+
    | preprocess  |  (micro-compact, drain bg, nag, auto-compact)
    +-----+------+
          |
    +-----v------+
    |  call_llm  |  (ChatAnthropic with bound tools)
    +-----+------+
          |
    +-----v------+
    |   router   |
    +--+------+--+
       |      |
  tool_calls  no_tools
       |      |
  +----v---+  |
  | tools  |  |
  +----+---+  |
       |      |
       +---+--+
           |
      +----v----+
      |   END   |
      +---------+
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from mini_claude_code.agent.nodes import (
    make_llm_node,
    make_tool_node,
    preprocess_node,
    route_response,
)
from mini_claude_code.agent.state import AgentState
from mini_claude_code.tools import get_all_tools


def build_agent_graph(tools: list | None = None):
    """Build and compile the main agent graph.

    Args:
        tools: Optional tool list. Defaults to get_all_tools().

    Returns:
        Compiled LangGraph runnable.
    """
    if tools is None:
        tools = get_all_tools()

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("call_llm", make_llm_node(tools))
    graph.add_node("tools", make_tool_node(tools))

    # Entry point
    graph.set_entry_point("preprocess")

    # Edges
    graph.add_edge("preprocess", "call_llm")
    graph.add_conditional_edges(
        "call_llm",
        route_response,
        {
            "tools": "tools",
            "end": END,
        },
    )
    graph.add_edge("tools", "preprocess")  # loop back

    return graph.compile()
