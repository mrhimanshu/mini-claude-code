"""Async team management tools (s09, s10, s11)."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from mini_claude_code.team.bus import MESSAGE_BUS
from mini_claude_code.team.manager import TEAMMATE_MANAGER
from mini_claude_code.team.protocols import (
    initiate_shutdown,
    review_plan,
)


@tool
async def spawn_teammate(name: str, role: str, prompt: str) -> str:
    """Spawn a named teammate agent that runs in the background.

    The teammate gets its own agent loop as an asyncio task with
    fresh context. It can read/write files, run commands, and
    communicate via the inbox system.

    Args:
        name: Unique name for the teammate (e.g. "alice").
        role: Role description (e.g. "coder", "tester").
        prompt: Initial task/instructions for the teammate.

    Returns:
        Confirmation of spawn or error.
    """
    return await TEAMMATE_MANAGER.spawn(name, role, prompt)


@tool
async def send_message(to: str, content: str) -> str:
    """Send a message to a teammate's inbox.

    Args:
        to: Name of the recipient teammate.
        content: Message content.

    Returns:
        Confirmation.
    """
    return await MESSAGE_BUS.send("lead", to, content)


@tool
async def read_inbox() -> str:
    """Read and drain the lead agent's inbox.

    Returns:
        JSON list of received messages, or empty list.
    """
    msgs = await MESSAGE_BUS.read_inbox("lead")
    if not msgs:
        return "(no messages)"
    return json.dumps(msgs, indent=2)


@tool
async def broadcast_message(content: str) -> str:
    """Broadcast a message to all teammates.

    Args:
        content: Message to broadcast.

    Returns:
        Confirmation with count.
    """
    members = await TEAMMATE_MANAGER.get_member_names()
    return await MESSAGE_BUS.broadcast("lead", content, members)


@tool
async def list_teammates() -> str:
    """List all teammates with their roles and statuses.

    Returns:
        Formatted teammate list.
    """
    return await TEAMMATE_MANAGER.list_members()


@tool
async def request_shutdown(teammate: str) -> str:
    """Request a teammate to shut down gracefully.

    Sends a shutdown_request to the teammate's inbox. The teammate
    can approve or reject. Use list_teammates to check status.

    Args:
        teammate: Name of the teammate to shut down.

    Returns:
        Request ID and status.
    """
    return await initiate_shutdown(teammate)


@tool
async def plan_approval(request_id: str, approve: bool, feedback: str = "") -> str:
    """Review and approve/reject a teammate's submitted plan.

    Args:
        request_id: The plan request ID to review.
        approve: True to approve, False to reject.
        feedback: Optional feedback for the teammate.

    Returns:
        Confirmation of approval/rejection.
    """
    return await review_plan(request_id, approve, feedback)
