"""Background task execution with daemon threads (s08)."""

from __future__ import annotations

import subprocess
import threading
import uuid

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR, BG_COMMAND_TIMEOUT


class BackgroundManager:
    """Runs commands in daemon threads with a notification queue."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self._notification_queue: list[dict] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def run(self, command: str) -> str:
        """Start a command in the background. Returns immediately."""
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "status": "running",
            "result": None,
            "command": command,
        }
        thread = threading.Thread(
            target=self._execute,
            args=(task_id, command),
            daemon=True,
        )
        thread.start()
        return f"Background task {task_id} started: {command}"

    # ------------------------------------------------------------------
    def _execute(self, task_id: str, command: str) -> None:
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=str(WORKDIR),
                capture_output=True,
                text=True,
                timeout=BG_COMMAND_TIMEOUT,
            )
            output = (r.stdout + r.stderr).strip()[:50_000]
            status = "completed"
        except subprocess.TimeoutExpired:
            output = f"Error: Timeout ({BG_COMMAND_TIMEOUT}s)"
            status = "timeout"
        except Exception as e:
            output = f"Error: {e}"
            status = "failed"

        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = output

        with self._lock:
            self._notification_queue.append(
                {
                    "task_id": task_id,
                    "command": command,
                    "status": status,
                    "result": output[:500],
                }
            )

    # ------------------------------------------------------------------
    def check(self, task_id: str) -> str:
        """Check the status of a background task."""
        task = self.tasks.get(task_id)
        if not task:
            return f"Error: Unknown background task '{task_id}'"
        result = task.get("result") or "(still running)"
        return f"[{task_id}] status={task['status']}\n{result}"

    # ------------------------------------------------------------------
    def drain_notifications(self) -> list[dict]:
        """Return and clear pending notifications (called before each LLM turn)."""
        with self._lock:
            notifs = list(self._notification_queue)
            self._notification_queue.clear()
        return notifs


# Singleton
BG_MANAGER = BackgroundManager()


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def background_run(command: str) -> str:
    """Run a long-running command in the background.

    The command runs in a separate thread. Use background_check to
    poll for results, or they will appear automatically before the
    next LLM call.

    Args:
        command: The shell command to execute.

    Returns:
        Task ID for tracking.
    """
    return BG_MANAGER.run(command)


@tool
def background_check(task_id: str) -> str:
    """Check the status of a background task.

    Args:
        task_id: The ID returned by background_run.

    Returns:
        Status and output of the background task.
    """
    return BG_MANAGER.check(task_id)
