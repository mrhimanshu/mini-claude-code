"""Async background task execution using asyncio.Task (s08).

Replaces threading with asyncio.create_subprocess_shell for true
async non-blocking execution. Notification queue is lock-protected.
"""

from __future__ import annotations

import asyncio
import uuid

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR, BG_COMMAND_TIMEOUT


class BackgroundManager:
    """Runs commands as asyncio tasks with a lock-protected notification queue."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self._notification_queue: list[dict] = []
        self._lock = asyncio.Lock()

    async def run(self, command: str) -> str:
        """Start a command in the background. Returns immediately."""
        task_id = str(uuid.uuid4())[:8]
        async with self._lock:
            self.tasks[task_id] = {
                "status": "running",
                "result": None,
                "command": command,
            }
        # Fire-and-forget asyncio task
        asyncio.create_task(self._execute(task_id, command))
        return f"Background task {task_id} started: {command}"

    async def _execute(self, task_id: str, command: str) -> None:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKDIR),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=BG_COMMAND_TIMEOUT
                )
                output = (
                    ((stdout or b"") + (stderr or b"")).decode(errors="replace").strip()
                )
                status = "completed"
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                output = f"Error: Timeout ({BG_COMMAND_TIMEOUT}s)"
                status = "timeout"
        except Exception as e:
            output = f"Error: {e}"
            status = "failed"

        output = output[:50_000]

        async with self._lock:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["result"] = output
            self._notification_queue.append(
                {
                    "task_id": task_id,
                    "command": command,
                    "status": status,
                    "result": output[:500],
                }
            )

    async def check(self, task_id: str) -> str:
        """Check the status of a background task."""
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return f"Error: Unknown background task '{task_id}'"
            result = task.get("result") or "(still running)"
            return f"[{task_id}] status={task['status']}\n{result}"

    async def drain_notifications(self) -> list[dict]:
        """Return and clear pending notifications."""
        async with self._lock:
            notifs = list(self._notification_queue)
            self._notification_queue.clear()
        return notifs

    async def list_tasks(self) -> dict[str, dict]:
        """Return a snapshot of all tasks."""
        async with self._lock:
            return dict(self.tasks)


# Singleton
BG_MANAGER = BackgroundManager()


# ---------------------------------------------------------------------------
# LangChain tools (all async)
# ---------------------------------------------------------------------------


@tool
async def background_run(command: str) -> str:
    """Run a long-running command in the background.

    The command runs as an asyncio task. Use background_check to poll
    for results, or they will appear automatically before the next
    LLM call.

    Args:
        command: The shell command to execute.

    Returns:
        Task ID for tracking.
    """
    return await BG_MANAGER.run(command)


@tool
async def background_check(task_id: str) -> str:
    """Check the status of a background task.

    Args:
        task_id: The ID returned by background_run.

    Returns:
        Status and output of the background task.
    """
    return await BG_MANAGER.check(task_id)
