"""Subagent: fresh-context child agent for isolated exploration (s04).

The subagent gets its own graph with a fresh message list and
restricted tools (no recursive spawning). Only the final text
response returns to the parent.
"""

from __future__ import annotations

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


def run_subagent(prompt: str) -> str:
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
            response = llm.invoke(messages)
        except Exception as e:
            return f"Subagent error: {e}"

        messages.append(response)

        if not isinstance(response, AIMessage) or not response.tool_calls:
            # Extract final text
            if isinstance(response, AIMessage) and response.content:
                return str(response.content)
            return "(subagent produced no output)"

        # Execute tool calls
        for tc in response.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                try:
                    result = tool_fn.invoke(tc["args"])
                except Exception as e:
                    result = f"Error: {e}"
            else:
                result = f"Unknown tool: {tc['name']}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return "(subagent reached iteration limit)"
