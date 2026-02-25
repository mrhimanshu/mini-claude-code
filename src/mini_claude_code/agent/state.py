"""LangGraph state definitions for the agent."""

from __future__ import annotations

from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State that flows through the LangGraph agent graph.

    messages         - conversation history (managed by add_messages reducer)
    rounds_since_todo - counter for nag-reminder injection (s03)
    should_compact   - flag set when token count exceeds threshold (s06)
    iteration_count  - safety counter to prevent infinite loops
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    rounds_since_todo: int
    should_compact: bool
    iteration_count: int
