"""Async file-based TaskManager with dependency graph (s07).

CRITICAL FIX: All operations are protected by asyncio.Lock to prevent
duplicate IDs and read-modify-write races on task JSON files.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from langchain_core.tools import tool

from mini_claude_code.config import TASKS_DIR


class TaskManager:
    """Persists tasks as JSON files in .tasks/ with dependency tracking.

    All public methods are async and lock-protected.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self.dir = tasks_dir
        self._next_id: int | None = None  # lazy-init on first create
        self._lock = asyncio.Lock()

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers (called under lock)
    # ------------------------------------------------------------------
    def _max_id(self) -> int:
        ids = []
        for f in self.dir.glob("task_*.json"):
            try:
                ids.append(int(f.stem.split("_")[1]))
            except (IndexError, ValueError):
                pass
        return max(ids) if ids else 0

    def _path(self, task_id: int) -> Path:
        return self.dir / f"task_{task_id}.json"

    def _load(self, task_id: int) -> dict:
        p = self._path(task_id)
        if not p.exists():
            raise FileNotFoundError(f"Task {task_id} not found")
        return json.loads(p.read_text())

    def _save(self, task: dict) -> None:
        self._path(task["id"]).write_text(json.dumps(task, indent=2))

    # ------------------------------------------------------------------
    # Public API (all async + locked)
    # ------------------------------------------------------------------
    async def create(self, subject: str, description: str = "") -> str:
        async with self._lock:
            self._ensure_dir()
            if self._next_id is None:
                self._next_id = self._max_id() + 1
            task = {
                "id": self._next_id,
                "subject": subject,
                "description": description,
                "status": "pending",
                "blockedBy": [],
                "blocks": [],
                "owner": "",
                "worktree": "",
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            await asyncio.to_thread(self._save, task)
            self._next_id += 1
            return json.dumps(task, indent=2)

    async def update(
        self,
        task_id: int,
        status: str | None = None,
        owner: str | None = None,
        add_blocked_by: list[int] | None = None,
        add_blocks: list[int] | None = None,
    ) -> str:
        async with self._lock:
            return await asyncio.to_thread(
                self._update_sync, task_id, status, owner, add_blocked_by, add_blocks
            )

    def _update_sync(
        self,
        task_id: int,
        status: str | None,
        owner: str | None,
        add_blocked_by: list[int] | None,
        add_blocks: list[int] | None,
    ) -> str:
        try:
            task = self._load(task_id)
        except FileNotFoundError as e:
            return str(e)

        if status:
            task["status"] = status
            if status == "completed":
                self._clear_dependency(task_id)

        if owner is not None:
            task["owner"] = owner

        if add_blocked_by:
            task["blockedBy"] = list(set(task.get("blockedBy", []) + add_blocked_by))

        if add_blocks:
            task["blocks"] = list(set(task.get("blocks", []) + add_blocks))
            for blocked_id in add_blocks:
                try:
                    blocked = self._load(blocked_id)
                    if task_id not in blocked.get("blockedBy", []):
                        blocked.setdefault("blockedBy", []).append(task_id)
                        self._save(blocked)
                except FileNotFoundError:
                    pass

        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)

    async def get(self, task_id: int) -> str:
        async with self._lock:
            self._ensure_dir()
            try:
                return json.dumps(self._load(task_id), indent=2)
            except FileNotFoundError as e:
                return str(e)

    async def list_all(self) -> str:
        async with self._lock:
            self._ensure_dir()
            return await asyncio.to_thread(self._list_all_sync)

    def _list_all_sync(self) -> str:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "(no tasks)"
        status_icons = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "cancelled": "[-]",
        }
        lines: list[str] = []
        for t in tasks:
            icon = status_icons.get(t["status"], "[ ]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" blocked_by={t['blockedBy']}" if t.get("blockedBy") else ""
            wt = f" wt={t['worktree']}" if t.get("worktree") else ""
            lines.append(f"{icon} #{t['id']}: {t['subject']}{owner}{blocked}{wt}")
        return "\n".join(lines)

    def _clear_dependency(self, completed_id: int) -> None:
        """Remove completed_id from all blockedBy lists. Called under lock."""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                task["updated_at"] = time.time()
                self._save(task)

    async def bind_worktree(self, task_id: int, worktree: str) -> str:
        async with self._lock:
            try:
                task = self._load(task_id)
            except FileNotFoundError as e:
                return str(e)
            task["worktree"] = worktree
            if task["status"] == "pending":
                task["status"] = "in_progress"
            task["updated_at"] = time.time()
            self._save(task)
            return f"Task {task_id} bound to worktree '{worktree}'"

    async def unbind_worktree(self, task_id: int) -> str:
        async with self._lock:
            try:
                task = self._load(task_id)
            except FileNotFoundError as e:
                return str(e)
            task["worktree"] = ""
            task["updated_at"] = time.time()
            self._save(task)
            return f"Task {task_id} unbound from worktree"

    async def scan_unclaimed(self) -> list[dict]:
        """Return pending, unowned, unblocked tasks. Lock-protected."""
        async with self._lock:
            return await asyncio.to_thread(self._scan_unclaimed_sync)

    def _scan_unclaimed_sync(self) -> list[dict]:
        if not self.dir.exists():
            return []
        unclaimed = []
        for f in sorted(self.dir.glob("task_*.json")):
            try:
                task = json.loads(f.read_text())
                if (
                    task.get("status") == "pending"
                    and not task.get("owner")
                    and not task.get("blockedBy")
                ):
                    unclaimed.append(task)
            except (json.JSONDecodeError, IOError):
                pass
        return unclaimed

    async def clear_all(self) -> str:
        """Delete all task files and reset ID counter."""
        async with self._lock:
            self._ensure_dir()
            count = 0
            for f in self.dir.glob("task_*.json"):
                try:
                    f.unlink()
                    count += 1
                except OSError:
                    pass
            self._next_id = 1
            return f"Cleared {count} tasks"

    async def claim_task(self, task_id: int, owner: str) -> bool:
        """Atomically claim a task. Returns True if claimed successfully."""
        async with self._lock:
            try:
                task = self._load(task_id)
            except FileNotFoundError:
                return False
            # Only claim if still unclaimed
            if task.get("status") != "pending" or task.get("owner"):
                return False
            task["status"] = "in_progress"
            task["owner"] = owner
            task["updated_at"] = time.time()
            self._save(task)
            return True


# Singleton
TASK_MANAGER = TaskManager(TASKS_DIR)


# ---------------------------------------------------------------------------
# LangChain tools (all async)
# ---------------------------------------------------------------------------


@tool
async def task_create(subject: str, description: str = "") -> str:
    """Create a new task on the task board.

    Args:
        subject: Short summary of what needs to be done.
        description: Optional longer description.

    Returns:
        JSON representation of the created task.
    """
    return await TASK_MANAGER.create(subject, description)


@tool
async def task_update(
    task_id: int,
    status: str | None = None,
    owner: str | None = None,
    add_blocked_by: list[int] | None = None,
    add_blocks: list[int] | None = None,
) -> str:
    """Update a task's status, owner, or dependencies.

    Args:
        task_id: The ID of the task to update.
        status: New status (pending, in_progress, completed, cancelled).
        owner: Assign an owner name.
        add_blocked_by: List of task IDs that block this task.
        add_blocks: List of task IDs that this task blocks.

    Returns:
        JSON representation of the updated task.
    """
    return await TASK_MANAGER.update(task_id, status, owner, add_blocked_by, add_blocks)


@tool
async def task_list() -> str:
    """List all tasks on the task board with their statuses and dependencies.

    Returns:
        Formatted task list.
    """
    return await TASK_MANAGER.list_all()


@tool
async def task_get(task_id: int) -> str:
    """Get full details of a specific task.

    Args:
        task_id: The ID of the task.

    Returns:
        JSON representation of the task.
    """
    return await TASK_MANAGER.get(task_id)
