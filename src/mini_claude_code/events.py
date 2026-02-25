"""Append-only event stream for lifecycle observability (s12)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mini_claude_code.config import WORKTREES_DIR


class EventStream:
    """Append-only JSONL event log."""

    def __init__(self, events_path: Path | None = None) -> None:
        self.path = events_path or (WORKTREES_DIR / "events.jsonl")

    def emit(self, event: str, **payload: Any) -> None:
        """Append an event to the log."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"event": event, "ts": time.time(), **payload}
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def list_recent(self, limit: int = 20) -> str:
        """Return the last *limit* events as formatted text."""
        if not self.path.exists():
            return "(no events)"
        lines = self.path.read_text().strip().splitlines()
        recent = lines[-limit:]
        events = []
        for line in recent:
            try:
                e = json.loads(line)
                events.append(e)
            except json.JSONDecodeError:
                pass
        if not events:
            return "(no events)"
        output: list[str] = []
        for e in events:
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            output.append(
                f"[{ts}] {e.get('event', '?')}: {json.dumps({k: v for k, v in e.items() if k not in ('event', 'ts')})}"
            )
        return "\n".join(output)


# Singleton
EVENT_STREAM = EventStream()
