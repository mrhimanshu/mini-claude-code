"""TodoManager for agent self-tracking with nag injection (s03)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


class TodoManager:
    """In-memory todo list with status tracking.

    Only one item may be ``in_progress`` at a time.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    def update(self, items: list[dict[str, Any]]) -> str:
        """Replace the full todo list.  Validates statuses."""
        validated: list[dict[str, Any]] = []
        in_progress_count = 0
        for item in items:
            status = item.get("status", "pending")
            if status not in ("pending", "in_progress", "completed", "cancelled"):
                status = "pending"
            if status == "in_progress":
                in_progress_count += 1
            validated.append(
                {
                    "content": item.get("content", item.get("text", "")),
                    "status": status,
                    "priority": item.get("priority", "medium"),
                }
            )
        if in_progress_count > 1:
            return "Error: Only one item can be in_progress at a time."
        self.items = validated
        return self.render()

    # ------------------------------------------------------------------
    def render(self) -> str:
        if not self.items:
            return "(no todos)"
        status_icons = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "cancelled": "[-]",
        }
        lines: list[str] = []
        for i, item in enumerate(self.items, 1):
            icon = status_icons.get(item["status"], "[ ]")
            pri = item.get("priority", "medium")
            lines.append(f"{icon} {i}. ({pri}) {item['content']}")
        return "\n".join(lines)


# Singleton
TODO_MANAGER = TodoManager()


@tool
def todo_write(todos: list[dict]) -> str:
    """Update the todo list for tracking multi-step tasks.

    Args:
        todos: List of todo items. Each item should have:
            - content (str): Brief description of the task
            - status (str): pending | in_progress | completed | cancelled
            - priority (str): high | medium | low

    Returns:
        Rendered todo list.
    """
    return TODO_MANAGER.update(todos)
