"""Async subagent: fresh-context child agent for isolated exploration (s04).

Uses ainvoke for non-blocking LLM calls and ainvoke for async tool execution.
"""

from __future__ import annotations

import asyncio

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from mini_claude_code.config import (
    ANTHROPIC_API_KEY,
    MAX_SUBAGENT_ITERATIONS,
    MODEL_NAME,
    WORKDIR,
)
from mini_claude_code.tools import get_child_tools


SUBAGENT_SYSTEM = (
    f"You are a subagent working at {WORKDIR}.\n"
    "Complete the task you are given and provide a clear, concise summary.\n"
    "You cannot spawn further subagents. Focus on the task and return results."
)


async def run_subagent(prompt: str) -> str:
    """Run a subagent with fresh context. Returns its final text summary."""
    tools = get_child_tools()
    tool_map = {t.name: t for t in tools}

    llm = ChatAnthropic(
        model_name=MODEL_NAME,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=8192,
        timeout=120,
        stop=None,
    ).bind_tools(tools)

    messages: list[BaseMessage] = [HumanMessage(content=prompt)]

    for _ in range(MAX_SUBAGENT_ITERATIONS):
        try:
            response = await llm.ainvoke(messages)
        except Exception as e:
            return f"Subagent error: {e}"

        messages.append(response)

        if not isinstance(response, AIMessage) or not response.tool_calls:
            if isinstance(response, AIMessage) and response.content:
                return str(response.content)
            return "(subagent produced no output)"

        # Execute tool calls in parallel
        async def _exec_tool(tc: dict) -> ToolMessage:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as e:
                    result = f"Error: {e}"
            else:
                result = f"Unknown tool: {tc['name']}"
            return ToolMessage(content=str(result), tool_call_id=tc["id"])

        tool_messages = await asyncio.gather(
            *[_exec_tool(tc) for tc in response.tool_calls]
        )
        messages.extend(tool_messages)

    return "(subagent reached iteration limit)"
