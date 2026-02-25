"""Tool registry - collects all tools and provides parent/child tool sets."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def get_all_tools() -> list[BaseTool]:
    """Return the full set of tools available to the parent (lead) agent."""
    from mini_claude_code.tools.bash_tool import bash_tool
    from mini_claude_code.tools.filesystem import read_file, write_file, edit_file
    from mini_claude_code.tools.todo import todo_write
    from mini_claude_code.tools.skills import load_skill
    from mini_claude_code.tools.compact import compact
    from mini_claude_code.tools.task_board import (
        task_create,
        task_update,
        task_list,
        task_get,
    )
    from mini_claude_code.tools.background import background_run, background_check
    from mini_claude_code.tools.subagent import delegate_task
    from mini_claude_code.tools.team import (
        spawn_teammate,
        send_message,
        read_inbox,
        broadcast_message,
        list_teammates,
        request_shutdown,
        plan_approval,
    )
    from mini_claude_code.tools.worktree import (
        worktree_create,
        worktree_list,
        worktree_status,
        worktree_run,
        worktree_keep,
        worktree_remove,
        worktree_events,
    )

    return [
        # Core (s01-s02)
        bash_tool,
        read_file,
        write_file,
        edit_file,
        # Todo (s03)
        todo_write,
        # Skills (s05)
        load_skill,
        # Compact (s06)
        compact,
        # Task board (s07)
        task_create,
        task_update,
        task_list,
        task_get,
        # Background (s08)
        background_run,
        background_check,
        # Subagent (s04)
        delegate_task,
        # Team (s09-s11)
        spawn_teammate,
        send_message,
        read_inbox,
        broadcast_message,
        list_teammates,
        request_shutdown,
        plan_approval,
        # Worktree (s12)
        worktree_create,
        worktree_list,
        worktree_status,
        worktree_run,
        worktree_keep,
        worktree_remove,
        worktree_events,
    ]


def get_child_tools() -> list[BaseTool]:
    """Return the restricted set of tools for subagents (no task/team/subagent)."""
    from mini_claude_code.tools.bash_tool import bash_tool
    from mini_claude_code.tools.filesystem import read_file, write_file, edit_file
    from mini_claude_code.tools.todo import todo_write
    from mini_claude_code.tools.skills import load_skill
    from mini_claude_code.tools.task_board import task_list, task_get

    return [
        bash_tool,
        read_file,
        write_file,
        edit_file,
        todo_write,
        load_skill,
        task_list,
        task_get,
    ]
