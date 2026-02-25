"""File-based TaskManager with dependency graph (s07)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from langchain_core.tools import tool

from mini_claude_code.config import TASKS_DIR


class TaskManager:
    """Persists tasks as JSON files in .tasks/ with dependency tracking."""

    def __init__(self, tasks_dir: Path) -> None:
        self.dir = tasks_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1

    # ------------------------------------------------------------------
    # Internal helpers
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
    # Public API
    # ------------------------------------------------------------------
    def create(self, subject: str, description: str = "") -> str:
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
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2)

    def update(
        self,
        task_id: int,
        status: str | None = None,
        owner: str | None = None,
        add_blocked_by: list[int] | None = None,
        add_blocks: list[int] | None = None,
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

    def get(self, task_id: int) -> str:
        try:
            return json.dumps(self._load(task_id), indent=2)
        except FileNotFoundError as e:
            return str(e)

    def list_all(self) -> str:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "(no tasks)"
        lines: list[str] = []
        status_icons = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "cancelled": "[-]",
        }
        for t in tasks:
            icon = status_icons.get(t["status"], "[ ]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" blocked_by={t['blockedBy']}" if t.get("blockedBy") else ""
            wt = f" wt={t['worktree']}" if t.get("worktree") else ""
            lines.append(f"{icon} #{t['id']}: {t['subject']}{owner}{blocked}{wt}")
        return "\n".join(lines)

    def _clear_dependency(self, completed_id: int) -> None:
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                task["updated_at"] = time.time()
                self._save(task)

    def bind_worktree(self, task_id: int, worktree: str) -> str:
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

    def unbind_worktree(self, task_id: int) -> str:
        try:
            task = self._load(task_id)
        except FileNotFoundError as e:
            return str(e)
        task["worktree"] = ""
        task["updated_at"] = time.time()
        self._save(task)
        return f"Task {task_id} unbound from worktree"


# Singleton
TASK_MANAGER = TaskManager(TASKS_DIR)


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def task_create(subject: str, description: str = "") -> str:
    """Create a new task on the task board.

    Args:
        subject: Short summary of what needs to be done.
        description: Optional longer description.

    Returns:
        JSON representation of the created task.
    """
    return TASK_MANAGER.create(subject, description)


@tool
def task_update(
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
    return TASK_MANAGER.update(task_id, status, owner, add_blocked_by, add_blocks)


@tool
def task_list() -> str:
    """List all tasks on the task board with their statuses and dependencies.

    Returns:
        Formatted task list.
    """
    return TASK_MANAGER.list_all()


@tool
def task_get(task_id: int) -> str:
    """Get full details of a specific task.

    Args:
        task_id: The ID of the task.

    Returns:
        JSON representation of the task.
    """
    return TASK_MANAGER.get(task_id)
