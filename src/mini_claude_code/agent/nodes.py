"""LangGraph nodes for the agent loop.

Graph structure:
  preprocess -> llm_call -> router -> [tools -> preprocess] | [END]
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from mini_claude_code.agent.state import AgentState
from mini_claude_code.config import (
    ANTHROPIC_API_KEY,
    MAX_AGENT_ITERATIONS,
    MAX_TOKENS,
    MODEL_NAME,
    NAG_ROUNDS_THRESHOLD,
    SYSTEM_PROMPT_TEMPLATE,
    WORKDIR,
)
from mini_claude_code.context.compactor import (
    auto_compact,
    estimate_tokens,
    micro_compact,
    needs_compaction,
)
from mini_claude_code.tools.background import BG_MANAGER
from mini_claude_code.tools.skills import SKILL_LOADER
from mini_claude_code.tools.todo import TODO_MANAGER


# ---------------------------------------------------------------------------
# Build the system prompt with skill descriptions
# ---------------------------------------------------------------------------


def _build_system_prompt() -> str:
    skills_desc = SKILL_LOADER.get_descriptions()
    skills_section = (
        f"Available skills (use load_skill to load full instructions):\n{skills_desc}"
        if skills_desc != "(no skills loaded)"
        else ""
    )
    return SYSTEM_PROMPT_TEMPLATE.format(
        workdir=WORKDIR,
        skills_section=skills_section,
    )


# ---------------------------------------------------------------------------
# Node: preprocess
# ---------------------------------------------------------------------------


def preprocess_node(state: AgentState) -> dict[str, Any]:
    """Pre-LLM-call processing: micro-compact, drain bg, nag injection.

    Runs before every LLM call in the loop.
    """
    messages = list(state["messages"])
    updates: dict[str, Any] = {}
    new_messages: list[BaseMessage] = []

    # --- Layer 1: micro-compact old tool results (s06) ---
    compact_updates = micro_compact(messages)
    if compact_updates:
        new_messages.extend(compact_updates)

    # --- Auto-compact if token count too high (s06 layer 2) ---
    if needs_compaction(messages):
        compact_msgs = auto_compact(messages)
        new_messages.extend(compact_msgs)
        updates["should_compact"] = False
        updates["rounds_since_todo"] = 0

    # --- Drain background notifications (s08) ---
    notifs = BG_MANAGER.drain_notifications()
    if notifs:
        notif_text = "\n".join(
            f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
        )
        new_messages.append(
            HumanMessage(
                content=f"<background-results>\n{notif_text}\n</background-results>"
            )
        )
        new_messages.append(AIMessage(content="Noted background results."))

    # --- Nag reminder for todo updates (s03) ---
    rounds = state.get("rounds_since_todo", 0)
    if rounds >= NAG_ROUNDS_THRESHOLD and TODO_MANAGER.items:
        new_messages.append(
            HumanMessage(
                content="<reminder>You have active todos. Please update their status.</reminder>"
            )
        )
        new_messages.append(AIMessage(content="I'll update my todos."))

    if new_messages:
        updates["messages"] = new_messages

    return updates


# ---------------------------------------------------------------------------
# Node: call_llm
# ---------------------------------------------------------------------------

# LLM singleton (lazy init)
_llm_instance: ChatAnthropic | None = None
_bound_llm: Any = None


def _get_bound_llm(tools: list) -> Any:
    global _llm_instance, _bound_llm
    if _bound_llm is None:
        _llm_instance = ChatAnthropic(
            model_name=MODEL_NAME,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=MAX_TOKENS,
            timeout=120,
            stop=None,
        )
        _bound_llm = _llm_instance.bind_tools(tools)
    return _bound_llm


def make_llm_node(tools: list):
    """Factory: returns a node function that calls the LLM with tools bound."""

    def llm_node(state: AgentState) -> dict[str, Any]:
        """Call the LLM with the current messages and tools."""
        bound = _get_bound_llm(tools)
        system_prompt = _build_system_prompt()

        messages = list(state["messages"])

        # Inject system prompt as first message if not present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages

        response = bound.invoke(messages)

        # Track todo usage
        rounds = state.get("rounds_since_todo", 0)
        used_todo = False
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] == "todo_write":
                    used_todo = True
                    break

        return {
            "messages": [response],
            "rounds_since_todo": 0 if used_todo else rounds + 1,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    return llm_node


# ---------------------------------------------------------------------------
# Node: execute_tools
# ---------------------------------------------------------------------------


def make_tool_node(tools: list):
    """Factory: returns a node that executes tool calls from the LLM response."""
    tool_map = {t.name: t for t in tools}

    def tool_node(state: AgentState) -> dict[str, Any]:
        """Execute all tool calls from the last AIMessage."""
        messages = state["messages"]
        last_msg = messages[-1]

        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return {}

        tool_messages: list[ToolMessage] = []
        for tc in last_msg.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                try:
                    result = tool_fn.invoke(tc["args"])
                except Exception as e:
                    result = f"Error executing {tc['name']}: {e}"
            else:
                result = f"Unknown tool: {tc['name']}"

            tool_messages.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tc["id"],
                )
            )

        return {"messages": tool_messages}

    return tool_node


# ---------------------------------------------------------------------------
# Router: conditional edge
# ---------------------------------------------------------------------------


def route_response(state: AgentState) -> Literal["tools", "end"]:
    """Route based on whether the LLM wants to call tools."""
    messages = state["messages"]
    if not messages:
        return "end"

    last_msg = messages[-1]

    # Safety: stop after too many iterations
    if state.get("iteration_count", 0) >= MAX_AGENT_ITERATIONS:
        return "end"

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "tools"

    return "end"
