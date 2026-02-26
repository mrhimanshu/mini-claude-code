"""Shutdown and plan approval protocol FSMs (s10).

Both protocols share the same request_id handshake pattern:
  pending -> approved | rejected

All tracker access is protected by asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from mini_claude_code.team.bus import MESSAGE_BUS


# ---------------------------------------------------------------------------
# Trackers (in-memory, lock-protected)
# ---------------------------------------------------------------------------

_lock = asyncio.Lock()
shutdown_requests: dict[str, dict[str, Any]] = {}
plan_requests: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Shutdown protocol
# ---------------------------------------------------------------------------


async def initiate_shutdown(teammate: str) -> str:
    """Lead requests a teammate to shut down gracefully."""
    req_id = str(uuid.uuid4())[:8]
    async with _lock:
        shutdown_requests[req_id] = {
            "target": teammate,
            "status": "pending",
        }
    await MESSAGE_BUS.send(
        "lead",
        teammate,
        "Please shut down gracefully.",
        "shutdown_request",
        {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to {teammate} (status: pending)"


async def handle_shutdown_response(req_id: str, approve: bool, reason: str = "") -> str:
    """Teammate responds to a shutdown request."""
    async with _lock:
        req = shutdown_requests.get(req_id)
        if not req:
            return f"Error: Unknown shutdown request '{req_id}'"
        req["status"] = "approved" if approve else "rejected"
        target = req["target"]
    await MESSAGE_BUS.send(
        target,
        "lead",
        reason,
        "shutdown_response",
        {"request_id": req_id, "approve": approve},
    )
    return f"Shutdown {'approved' if approve else 'rejected'} for request {req_id}"


# ---------------------------------------------------------------------------
# Plan approval protocol
# ---------------------------------------------------------------------------


async def submit_plan(sender: str, plan_text: str) -> str:
    """Teammate submits a plan for lead approval."""
    req_id = str(uuid.uuid4())[:8]
    async with _lock:
        plan_requests[req_id] = {
            "from": sender,
            "plan": plan_text,
            "status": "pending",
        }
    await MESSAGE_BUS.send(
        sender,
        "lead",
        plan_text,
        "plan_approval_request",
        {"request_id": req_id, "plan": plan_text},
    )
    return f"Plan submitted (request_id={req_id}), awaiting lead approval"


async def review_plan(request_id: str, approve: bool, feedback: str = "") -> str:
    """Lead reviews and approves/rejects a submitted plan."""
    async with _lock:
        req = plan_requests.get(request_id)
        if not req:
            return f"Error: Unknown plan request '{request_id}'"
        req["status"] = "approved" if approve else "rejected"
        sender = req["from"]
    await MESSAGE_BUS.send(
        "lead",
        sender,
        feedback,
        "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {'approved' if approve else 'rejected'} for {sender}"
