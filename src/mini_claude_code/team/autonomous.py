"""Autonomous agent helpers (s11).

Provides task board scanning and claiming utilities used by
the TeammateManager's idle polling loop.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from mini_claude_code.config import TASKS_DIR


def scan_unclaimed_tasks() -> list[dict]:
    """Find pending, unowned, unblocked tasks on the board."""
    if not TASKS_DIR.exists():
        return []
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
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


def claim_task(task_id: int, owner: str) -> None:
    """Claim a task by setting its owner and status."""
    path = TASKS_DIR / f"task_{task_id}.json"
    if not path.exists():
        return
    task = json.loads(path.read_text())
    task["status"] = "in_progress"
    task["owner"] = owner
    task["updated_at"] = time.time()
    path.write_text(json.dumps(task, indent=2))
