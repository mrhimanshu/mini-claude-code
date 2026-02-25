"""Git worktree management with task binding (s12)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR, WORKTREES_DIR, BG_COMMAND_TIMEOUT
from mini_claude_code.events import EVENT_STREAM
from mini_claude_code.tools.task_board import TASK_MANAGER


class WorktreeManager:
    """Manages git worktrees bound to tasks by ID."""

    def __init__(self, worktrees_dir: Path | None = None) -> None:
        self.dir = worktrees_dir or WORKTREES_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------
    def _load_index(self) -> dict:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {"worktrees": []}

    def _save_index(self, idx: dict) -> None:
        self.index_path.write_text(json.dumps(idx, indent=2))

    def _find(self, name: str) -> dict | None:
        idx = self._load_index()
        for wt in idx["worktrees"]:
            if wt["name"] == name:
                return wt
        return None

    def _run_git(self, args: list[str]) -> str:
        r = subprocess.run(
            ["git"] + args,
            cwd=str(WORKDIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
        return r.stdout.strip()

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def create(
        self, name: str, task_id: int | None = None, base_ref: str = "HEAD"
    ) -> str:
        """Create a worktree with an isolated directory and branch."""
        if self._find(name):
            return f"Error: Worktree '{name}' already exists"

        path = self.dir / name
        branch = f"wt/{name}-{int(time.time())}"

        EVENT_STREAM.emit(
            "worktree.create.before", worktree={"name": name, "path": str(path)}
        )

        try:
            self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])
        except RuntimeError as e:
            EVENT_STREAM.emit(
                "worktree.create.failed", worktree={"name": name}, error=str(e)
            )
            return f"Error creating worktree: {e}"

        entry = {
            "name": name,
            "path": str(path),
            "branch": branch,
            "task_id": task_id,
            "status": "active",
            "created_at": time.time(),
        }
        idx = self._load_index()
        idx["worktrees"].append(entry)
        self._save_index(idx)

        if task_id is not None:
            TASK_MANAGER.bind_worktree(task_id, name)

        EVENT_STREAM.emit("worktree.create.after", worktree=entry)
        return f"Created worktree '{name}' at {path} (branch: {branch})"

    def remove(
        self, name: str, force: bool = False, complete_task: bool = False
    ) -> str:
        """Remove a worktree and optionally complete its bound task."""
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"

        EVENT_STREAM.emit(
            "worktree.remove.before",
            task={"id": wt.get("task_id")} if wt.get("task_id") is not None else {},
            worktree={"name": name, "path": wt.get("path")},
        )

        try:
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(wt["path"])
            self._run_git(args)

            if complete_task and wt.get("task_id") is not None:
                task_id = wt["task_id"]
                TASK_MANAGER.update(task_id, status="completed")
                TASK_MANAGER.unbind_worktree(task_id)
                EVENT_STREAM.emit("task.completed", task={"id": task_id})

            idx = self._load_index()
            for item in idx.get("worktrees", []):
                if item.get("name") == name:
                    item["status"] = "removed"
                    item["removed_at"] = time.time()
            self._save_index(idx)

            EVENT_STREAM.emit(
                "worktree.remove.after", worktree={"name": name, "status": "removed"}
            )
            return f"Removed worktree '{name}'"
        except Exception as e:
            EVENT_STREAM.emit(
                "worktree.remove.failed", worktree={"name": name}, error=str(e)
            )
            return f"Error removing worktree: {e}"

    def keep(self, name: str) -> str:
        """Mark a worktree as kept (preserved but lifecycle complete)."""
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        idx = self._load_index()
        for item in idx["worktrees"]:
            if item["name"] == name:
                item["status"] = "kept"
        self._save_index(idx)
        EVENT_STREAM.emit("worktree.keep", worktree={"name": name})
        return f"Worktree '{name}' marked as kept"

    def run(self, name: str, command: str) -> str:
        """Run a command inside a worktree directory."""
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=wt["path"],
                capture_output=True,
                text=True,
                timeout=BG_COMMAND_TIMEOUT,
            )
            output = (r.stdout + r.stderr).strip()
            return output[:50_000] if output else "(no output)"
        except Exception as e:
            return f"Error: {e}"

    def status(self, name: str) -> str:
        """Get git status inside a worktree."""
        return self.run(name, "git status --short")

    def list_all(self) -> str:
        """List all worktrees."""
        idx = self._load_index()
        if not idx["worktrees"]:
            return "(no worktrees)"
        lines = []
        for wt in idx["worktrees"]:
            task_str = (
                f" task=#{wt['task_id']}" if wt.get("task_id") is not None else ""
            )
            lines.append(
                f"  {wt['name']} [{wt['status']}] branch={wt['branch']}{task_str}"
            )
        return "\n".join(lines)


# Singleton
WORKTREE_MANAGER = WorktreeManager()


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def worktree_create(name: str, task_id: int | None = None) -> str:
    """Create an isolated git worktree, optionally bound to a task.

    Args:
        name: Name for the worktree (used as directory name).
        task_id: Optional task ID to bind to (auto-advances task to in_progress).

    Returns:
        Confirmation with path and branch info.
    """
    return WORKTREE_MANAGER.create(name, task_id)


@tool
def worktree_list() -> str:
    """List all worktrees with their status and task bindings.

    Returns:
        Formatted worktree list.
    """
    return WORKTREE_MANAGER.list_all()


@tool
def worktree_status(name: str) -> str:
    """Get git status inside a worktree.

    Args:
        name: Name of the worktree.

    Returns:
        Short git status output.
    """
    return WORKTREE_MANAGER.status(name)


@tool
def worktree_run(name: str, command: str) -> str:
    """Run a command inside a worktree's directory.

    Args:
        name: Name of the worktree.
        command: Shell command to run.

    Returns:
        Command output.
    """
    return WORKTREE_MANAGER.run(name, command)


@tool
def worktree_keep(name: str) -> str:
    """Mark a worktree as kept (preserve directory, complete lifecycle).

    Args:
        name: Name of the worktree.

    Returns:
        Confirmation.
    """
    return WORKTREE_MANAGER.keep(name)


@tool
def worktree_remove(name: str, force: bool = False, complete_task: bool = False) -> str:
    """Remove a worktree and optionally complete its bound task.

    Args:
        name: Name of the worktree.
        force: Force removal even if dirty.
        complete_task: If True, also mark the bound task as completed.

    Returns:
        Confirmation.
    """
    return WORKTREE_MANAGER.remove(name, force, complete_task)


@tool
def worktree_events(limit: int = 20) -> str:
    """Query the worktree event stream.

    Args:
        limit: Number of recent events to return (default 20).

    Returns:
        Formatted event log.
    """
    return EVENT_STREAM.list_recent(limit)
