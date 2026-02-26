"""Async git worktree management with task binding (s12).

All operations are lock-protected and use asyncio subprocess.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR, WORKTREES_DIR, BG_COMMAND_TIMEOUT
from mini_claude_code.events import EVENT_STREAM
from mini_claude_code.tools.task_board import TASK_MANAGER


class WorktreeManager:
    """Manages git worktrees bound to tasks by ID. Fully async + locked."""

    def __init__(self, worktrees_dir: Path | None = None) -> None:
        self.dir = worktrees_dir or WORKTREES_DIR
        self.index_path = self.dir / "index.json"
        self._lock = asyncio.Lock()

    async def _ensure_dir(self) -> None:
        await asyncio.to_thread(self.dir.mkdir, parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Index management (called under lock)
    # ------------------------------------------------------------------
    def _load_index_sync(self) -> dict:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {"worktrees": []}

    def _save_index_sync(self, idx: dict) -> None:
        self.index_path.write_text(json.dumps(idx, indent=2))

    def _find_sync(self, name: str) -> dict | None:
        idx = self._load_index_sync()
        for wt in idx["worktrees"]:
            if wt["name"] == name:
                return wt
        return None

    async def _run_git(self, args: list[str]) -> str:
        """Run a git command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKDIR),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace").strip()
            out = (stdout or b"").decode(errors="replace").strip()
            raise RuntimeError(err or out)
        return (stdout or b"").decode(errors="replace").strip()

    # ------------------------------------------------------------------
    # Operations (all async + locked)
    # ------------------------------------------------------------------
    async def create(
        self, name: str, task_id: int | None = None, base_ref: str = "HEAD"
    ) -> str:
        async with self._lock:
            await self._ensure_dir()

            if self._find_sync(name):
                return f"Error: Worktree '{name}' already exists"

            path = self.dir / name
            branch = f"wt/{name}-{int(time.time())}"

            await EVENT_STREAM.emit(
                "worktree.create.before", worktree={"name": name, "path": str(path)}
            )

            try:
                await self._run_git(
                    ["worktree", "add", "-b", branch, str(path), base_ref]
                )
            except RuntimeError as e:
                await EVENT_STREAM.emit(
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
            idx = self._load_index_sync()
            idx["worktrees"].append(entry)
            self._save_index_sync(idx)

        # Bind task outside the worktree lock (task_board has its own lock)
        if task_id is not None:
            await TASK_MANAGER.bind_worktree(task_id, name)

        await EVENT_STREAM.emit("worktree.create.after", worktree=entry)
        return f"Created worktree '{name}' at {path} (branch: {branch})"

    async def remove(
        self, name: str, force: bool = False, complete_task: bool = False
    ) -> str:
        async with self._lock:
            wt = self._find_sync(name)
            if not wt:
                return f"Error: Unknown worktree '{name}'"

            await EVENT_STREAM.emit(
                "worktree.remove.before",
                task={"id": wt.get("task_id")} if wt.get("task_id") is not None else {},
                worktree={"name": name, "path": wt.get("path")},
            )

            try:
                args = ["worktree", "remove"]
                if force:
                    args.append("--force")
                args.append(wt["path"])
                await self._run_git(args)

                idx = self._load_index_sync()
                for item in idx.get("worktrees", []):
                    if item.get("name") == name:
                        item["status"] = "removed"
                        item["removed_at"] = time.time()
                self._save_index_sync(idx)

                task_id = wt.get("task_id")
            except Exception as e:
                await EVENT_STREAM.emit(
                    "worktree.remove.failed", worktree={"name": name}, error=str(e)
                )
                return f"Error removing worktree: {e}"

        # Task operations outside worktree lock
        if complete_task and task_id is not None:
            await TASK_MANAGER.update(task_id, status="completed")
            await TASK_MANAGER.unbind_worktree(task_id)
            await EVENT_STREAM.emit("task.completed", task={"id": task_id})

        await EVENT_STREAM.emit(
            "worktree.remove.after", worktree={"name": name, "status": "removed"}
        )
        return f"Removed worktree '{name}'"

    async def keep(self, name: str) -> str:
        async with self._lock:
            wt = self._find_sync(name)
            if not wt:
                return f"Error: Unknown worktree '{name}'"
            idx = self._load_index_sync()
            for item in idx["worktrees"]:
                if item["name"] == name:
                    item["status"] = "kept"
            self._save_index_sync(idx)
        await EVENT_STREAM.emit("worktree.keep", worktree={"name": name})
        return f"Worktree '{name}' marked as kept"

    async def run(self, name: str, command: str) -> str:
        async with self._lock:
            wt = self._find_sync(name)
            if not wt:
                return f"Error: Unknown worktree '{name}'"
            wt_path = wt["path"]

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=wt_path,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=BG_COMMAND_TIMEOUT
            )
            output = (
                ((stdout or b"") + (stderr or b"")).decode(errors="replace").strip()
            )
            return output[:50_000] if output else "(no output)"
        except Exception as e:
            return f"Error: {e}"

    async def status(self, name: str) -> str:
        return await self.run(name, "git status --short")

    async def list_all(self) -> str:
        async with self._lock:
            idx = self._load_index_sync()
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
# LangChain tools (all async)
# ---------------------------------------------------------------------------


@tool
async def worktree_create(name: str, task_id: int | None = None) -> str:
    """Create an isolated git worktree, optionally bound to a task.

    Args:
        name: Name for the worktree (used as directory name).
        task_id: Optional task ID to bind to (auto-advances task to in_progress).

    Returns:
        Confirmation with path and branch info.
    """
    return await WORKTREE_MANAGER.create(name, task_id)


@tool
async def worktree_list() -> str:
    """List all worktrees with their status and task bindings.

    Returns:
        Formatted worktree list.
    """
    return await WORKTREE_MANAGER.list_all()


@tool
async def worktree_status(name: str) -> str:
    """Get git status inside a worktree.

    Args:
        name: Name of the worktree.

    Returns:
        Short git status output.
    """
    return await WORKTREE_MANAGER.status(name)


@tool
async def worktree_run(name: str, command: str) -> str:
    """Run a command inside a worktree's directory.

    Args:
        name: Name of the worktree.
        command: Shell command to run.

    Returns:
        Command output.
    """
    return await WORKTREE_MANAGER.run(name, command)


@tool
async def worktree_keep(name: str) -> str:
    """Mark a worktree as kept (preserve directory, complete lifecycle).

    Args:
        name: Name of the worktree.

    Returns:
        Confirmation.
    """
    return await WORKTREE_MANAGER.keep(name)


@tool
async def worktree_remove(
    name: str, force: bool = False, complete_task: bool = False
) -> str:
    """Remove a worktree and optionally complete its bound task.

    Args:
        name: Name of the worktree.
        force: Force removal even if dirty.
        complete_task: If True, also mark the bound task as completed.

    Returns:
        Confirmation.
    """
    return await WORKTREE_MANAGER.remove(name, force, complete_task)


@tool
async def worktree_events(limit: int = 20) -> str:
    """Query the worktree event stream.

    Args:
        limit: Number of recent events to return (default 20).

    Returns:
        Formatted event log.
    """
    return await EVENT_STREAM.list_recent(limit)
