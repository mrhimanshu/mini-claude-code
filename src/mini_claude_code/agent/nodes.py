"""Async LangGraph nodes for the agent loop.

All nodes are async. Tool execution uses asyncio.gather for parallel
execution of multiple tool calls. LLM calls use ainvoke.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import RunnableConfig
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
    PLAN_SYSTEM_PROMPT_TEMPLATE,
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
# System prompt with skill descriptions
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
# Node: preprocess (async)
# ---------------------------------------------------------------------------


async def preprocess_node(state: AgentState) -> dict[str, Any]:
    """Pre-LLM-call processing: micro-compact, drain bg, nag injection."""
    messages = list(state["messages"])
    updates: dict[str, Any] = {}
    new_messages: list[BaseMessage] = []

    # Layer 1: micro-compact old tool results
    compact_updates = micro_compact(messages)
    if compact_updates:
        new_messages.extend(compact_updates)

    # Layer 2: auto-compact if token count too high
    if needs_compaction(messages):
        compact_msgs = await auto_compact(messages)
        new_messages.extend(compact_msgs)
        updates["should_compact"] = False
        updates["rounds_since_todo"] = 0

    # Drain background notifications (async)
    # NOTE: Only inject HumanMessages here — never fake AIMessages.
    # The LLM will see these as system-injected context on its next turn.
    # Injecting AIMessage pairs risks creating consecutive assistant
    # messages which violate the Anthropic API's role-alternation rule.
    notifs = await BG_MANAGER.drain_notifications()
    if notifs:
        notif_text = "\n".join(
            f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
        )
        new_messages.append(
            HumanMessage(
                content=f"<background-results>\n{notif_text}\n</background-results>"
            )
        )

    # Nag reminder for todo updates
    rounds = state.get("rounds_since_todo", 0)
    if rounds >= NAG_ROUNDS_THRESHOLD and TODO_MANAGER.items:
        # Append to bg message if present, otherwise add standalone
        nag_text = (
            "<reminder>You have active todos. Please update their status.</reminder>"
        )
        if new_messages and isinstance(new_messages[-1], HumanMessage):
            # Merge into the last HumanMessage to avoid consecutive user msgs
            new_messages[-1] = HumanMessage(
                content=str(new_messages[-1].content) + "\n\n" + nag_text
            )
        else:
            new_messages.append(HumanMessage(content=nag_text))

    if new_messages:
        updates["messages"] = new_messages
    return updates


# ---------------------------------------------------------------------------
# Node: call_llm (async, uses ainvoke)
# ---------------------------------------------------------------------------

_llm_instance: ChatAnthropic | None = None
_bound_llm: Any = None
_llm_lock = asyncio.Lock()


async def _get_bound_llm(tools: list) -> Any:
    """Get or create the bound LLM (lock-protected lazy init)."""
    global _llm_instance, _bound_llm
    async with _llm_lock:
        if _bound_llm is None:
            _llm_instance = ChatAnthropic(
                model_name=MODEL_NAME,
                api_key=ANTHROPIC_API_KEY,
                max_tokens=MAX_TOKENS,
                timeout=120,
                stop=None,
                streaming=True,
            )
            _bound_llm = _llm_instance.bind_tools(tools)
    return _bound_llm


def _sanitize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Ensure every tool_use block has a matching tool_result.

    If a ToolMessage was lost (e.g. by a faulty compaction), we insert a
    placeholder so the Anthropic API doesn't reject the request.  Also
    collapses consecutive same-role messages that could confuse the API.
    """
    # Collect all tool_call_ids that have a ToolMessage
    present_result_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            present_result_ids.add(msg.tool_call_id)

    # Find orphaned tool_use ids (AI message has tool_calls but no result)
    missing: list[tuple[int, str]] = []  # (insert_after_index, tool_call_id)
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id") or tc.get("id", "unknown")
                if tc_id and tc_id not in present_result_ids:
                    missing.append((i, str(tc_id)))

    if not missing:
        return messages

    # Insert placeholder ToolMessages right after their AIMessage
    patched = list(messages)
    offset = 0
    for insert_after, tc_id in missing:
        pos = insert_after + 1 + offset
        patched.insert(
            pos,
            ToolMessage(
                content="[tool result unavailable — context was compacted]",
                tool_call_id=tc_id,
            ),
        )
        offset += 1
    return patched


def make_llm_node(tools: list):
    """Factory: returns an async node that calls the LLM."""

    async def llm_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        bound = await _get_bound_llm(tools)
        system_prompt = _build_system_prompt()

        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages

        # Safety: repair any orphaned tool_use blocks before calling the API
        messages = _sanitize_messages(messages)

        response = await bound.ainvoke(messages, config=config)

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
# Node: execute_tools (async, parallel via asyncio.gather)
# ---------------------------------------------------------------------------


def make_tool_node(tools: list):
    """Factory: returns an async node that executes tool calls in parallel."""
    tool_map = {t.name: t for t in tools}

    async def tool_node(state: AgentState) -> dict[str, Any]:
        messages = state["messages"]
        last_msg = messages[-1]

        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return {}

        async def _exec_one(tc: dict) -> ToolMessage:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as e:
                    result = f"Error executing {tc['name']}: {e}"
            else:
                result = f"Unknown tool: {tc['name']}"
            return ToolMessage(content=str(result), tool_call_id=tc["id"])

        # Execute ALL tool calls in parallel
        tool_messages = await asyncio.gather(
            *[_exec_one(tc) for tc in last_msg.tool_calls]
        )

        return {"messages": list(tool_messages)}

    return tool_node


# ---------------------------------------------------------------------------
# Router: conditional edge
# ---------------------------------------------------------------------------


def route_response(state: AgentState) -> Literal["tools", "end"]:
    messages = state["messages"]
    if not messages:
        return "end"
    last_msg = messages[-1]
    if state.get("iteration_count", 0) >= MAX_AGENT_ITERATIONS:
        return "end"
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "tools"
    return "end"


# ---------------------------------------------------------------------------
# Plan mode LLM node (no tools, structured output)
# ---------------------------------------------------------------------------

_plan_llm_instance: ChatAnthropic | None = None
_plan_llm_lock = asyncio.Lock()


async def _get_plan_llm() -> ChatAnthropic:
    """Get or create the plan-mode LLM (no tools bound)."""
    global _plan_llm_instance
    async with _plan_llm_lock:
        if _plan_llm_instance is None:
            _plan_llm_instance = ChatAnthropic(
                model_name=MODEL_NAME,
                api_key=ANTHROPIC_API_KEY,
                max_tokens=MAX_TOKENS,
                timeout=120,
                stop=None,
                streaming=True,
            )
    return _plan_llm_instance


def _build_plan_system_prompt() -> str:
    """Build the system prompt for plan mode."""
    skills_desc = SKILL_LOADER.get_descriptions()
    skills_section = (
        f"Available skills (use load_skill to load full instructions):\n{skills_desc}"
        if skills_desc != "(no skills loaded)"
        else ""
    )
    return PLAN_SYSTEM_PROMPT_TEMPLATE.format(
        workdir=WORKDIR,
        skills_section=skills_section,
    )


def make_plan_llm_node():
    """Factory: returns an async node for plan-mode LLM calls (no tools)."""

    async def plan_llm_node(
        state: AgentState, config: RunnableConfig
    ) -> dict[str, Any]:
        llm = await _get_plan_llm()
        system_prompt = _build_plan_system_prompt()

        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages

        response = await llm.ainvoke(messages, config=config)

        return {
            "messages": [response],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    return plan_llm_node
