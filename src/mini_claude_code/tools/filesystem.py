"""Async file system tools with path sandboxing and locking (s02).

edit_file uses an asyncio.Lock to make the read-check-write atomic,
preventing concurrent edits from losing data.

When REQUIRE_APPROVAL is enabled (default), write_file and edit_file
show a colored unified diff and prompt the user for approval before
writing to disk.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR
from mini_claude_code.tools.approval import request_approval

# Per-file locks for atomic edit operations
_edit_locks: dict[str, asyncio.Lock] = {}
_edit_locks_guard = asyncio.Lock()


async def _get_edit_lock(path: str) -> asyncio.Lock:
    """Get or create a per-file lock for edit atomicity."""
    async with _edit_locks_guard:
        if path not in _edit_locks:
            _edit_locks[path] = asyncio.Lock()
        return _edit_locks[path]


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def safe_path(p: str) -> Path:
    """Resolve *p* relative to WORKDIR and ensure it doesn't escape."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
async def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
    """Read a file from the workspace.

    Args:
        path: Relative path to the file.
        offset: Line number to start from (1-indexed, default 1).
        limit: Maximum number of lines to return (default 2000).

    Returns:
        File contents with line numbers, or an error message.
    """
    try:
        target = safe_path(path)

        def _read() -> str:
            if target.is_dir():
                entries = []
                for entry in sorted(target.iterdir()):
                    name = entry.name + ("/" if entry.is_dir() else "")
                    entries.append(name)
                return "\n".join(entries) if entries else "(empty directory)"

            text = target.read_text(errors="replace")
            lines = text.splitlines()
            start = max(0, offset - 1)
            end = start + limit
            selected = lines[start:end]
            numbered = [f"{start + i + 1}: {line}" for i, line in enumerate(selected)]
            result = "\n".join(numbered)
            if len(result) > 50_000:
                result = result[:50_000] + "\n... [truncated]"
            return result

        return await asyncio.to_thread(_read)
    except Exception as e:
        return f"Error: {e}"


@tool
async def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace (creates parent dirs).

    Args:
        path: Relative path to the file.
        content: Full content to write.

    Returns:
        Confirmation or error message.
    """
    try:
        target = safe_path(path)

        # Read existing content for diffing (empty string if new file)
        old_content = ""
        operation = "create"
        if target.exists():
            old_content = await asyncio.to_thread(target.read_text, "utf-8")
            operation = "write"

        approved = await request_approval(
            path, old_content, content, operation=operation
        )
        if not approved:
            return f"Rejected: write to {path} was rejected by the user."

        def _write() -> str:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            return f"Wrote {len(content)} chars to {path}"

        return await asyncio.to_thread(_write)
    except Exception as e:
        return f"Error: {e}"


@tool
async def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace an exact string in a file (atomic read-check-write).

    Args:
        path: Relative path to the file.
        old_text: The exact text to find and replace.
        new_text: The replacement text.

    Returns:
        Confirmation or error message.
    """
    try:
        target = safe_path(path)
        lock = await _get_edit_lock(str(target))

        async with lock:
            # Read current content and validate before asking for approval
            content = await asyncio.to_thread(target.read_text)
            count = content.count(old_text)
            if count == 0:
                return f"Error: old_text not found in {path}"
            if count > 1:
                return (
                    f"Error: Found {count} matches for old_text in {path}. "
                    "Provide more context to make it unique."
                )

            new_content = content.replace(old_text, new_text, 1)

            # Show diff and request approval
            approved = await request_approval(
                path, content, new_content, operation="edit"
            )
            if not approved:
                return f"Rejected: edit to {path} was rejected by the user."

            await asyncio.to_thread(target.write_text, new_content)
            return f"Edited {path} (replaced 1 occurrence)"
    except Exception as e:
        return f"Error: {e}"
