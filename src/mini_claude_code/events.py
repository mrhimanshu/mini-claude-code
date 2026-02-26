"""Append-only event stream for lifecycle observability (s12).

Thread-safe via asyncio.Lock. All public methods are async.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from mini_claude_code.config import WORKTREES_DIR


class EventStream:
    """Append-only JSONL event log with async locking."""

    def __init__(self, events_path: Path | None = None) -> None:
        self.path = events_path or (WORKTREES_DIR / "events.jsonl")
        self._lock = asyncio.Lock()

    async def emit(self, event: str, **payload: Any) -> None:
        """Append an event to the log (lock-protected)."""
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entry = {"event": event, "ts": time.time(), **payload}
            await asyncio.to_thread(self._append, entry)

    def _append(self, entry: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    async def list_recent(self, limit: int = 20) -> str:
        """Return the last *limit* events as formatted text."""
        async with self._lock:
            return await asyncio.to_thread(self._read_recent, limit)

    def _read_recent(self, limit: int) -> str:
        if not self.path.exists():
            return "(no events)"
        lines = self.path.read_text().strip().splitlines()
        recent = lines[-limit:]
        events = []
        for line in recent:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if not events:
            return "(no events)"
        output: list[str] = []
        for e in events:
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            payload = {k: v for k, v in e.items() if k not in ("event", "ts")}
            output.append(f"[{ts}] {e.get('event', '?')}: {json.dumps(payload)}")
        return "\n".join(output)


# Singleton
EVENT_STREAM = EventStream()
