"""Async subagent tool: spawn a fresh-context child agent (s04)."""

from __future__ import annotations

from langchain_core.tools import tool


@tool
async def delegate_task(prompt: str, description: str = "") -> str:
    """Spawn a subagent with fresh context to handle a task.

    The subagent starts with no conversation history (clean context).
    It has access to file and bash tools but cannot spawn further
    subagents. Only its final text response returns to you.

    Use this for exploratory tasks (reading many files, searching
    the codebase) to keep your own context clean.

    Args:
        prompt: Detailed instructions for the subagent.
        description: Short description of the task (for logging).

    Returns:
        The subagent's final text summary.
    """
    from mini_claude_code.agent.subagent import run_subagent

    return await run_subagent(prompt)
