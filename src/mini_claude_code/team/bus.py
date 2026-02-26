"""JSONL-based message bus for inter-agent communication (s09).

Uses **per-inbox locks** so that operations on different inboxes can
proceed in parallel (e.g. teammate A reading its inbox does not block
teammate B from reading its own inbox).

read_inbox is atomic: the lock on a given inbox protects the
read+drain sequence so no messages are lost between read_text and
write_text.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from mini_claude_code.config import INBOX_DIR


class MessageBus:
    """Append-only JSONL inbox per agent with per-inbox locking."""

    def __init__(self, inbox_dir: Path | None = None) -> None:
        self.dir = inbox_dir or INBOX_DIR
        # Per-inbox locks: key = inbox name, value = asyncio.Lock
        self._inbox_locks: dict[str, asyncio.Lock] = {}
        # Meta-lock protects only the _inbox_locks dict itself
        self._meta_lock = asyncio.Lock()

    async def _ensure_dir(self) -> None:
        await asyncio.to_thread(self.dir.mkdir, parents=True, exist_ok=True)

    async def _get_lock(self, name: str) -> asyncio.Lock:
        """Get (or create) the lock for a specific inbox."""
        async with self._meta_lock:
            if name not in self._inbox_locks:
                self._inbox_locks[name] = asyncio.Lock()
            return self._inbox_locks[name]

    # ------------------------------------------------------------------
    async def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Append a message to *to*'s inbox (per-inbox lock)."""
        msg: dict[str, Any] = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)

        await self._ensure_dir()
        lock = await self._get_lock(to)
        async with lock:
            inbox = self.dir / f"{to}.jsonl"
            await asyncio.to_thread(self._atomic_append, inbox, msg)
        return f"Sent {msg_type} to {to}"

    @staticmethod
    def _atomic_append(path: Path, msg: dict) -> None:
        with open(path, "a") as f:
            f.write(json.dumps(msg) + "\n")

    # ------------------------------------------------------------------
    async def read_inbox(self, name: str) -> list[dict]:
        """Atomically read and drain all messages from *name*'s inbox.

        The per-inbox lock ensures no send() to this same inbox can
        interleave between the read and the drain, fixing the TOCTOU
        message-loss bug — while NOT blocking other inboxes.
        """
        await self._ensure_dir()
        lock = await self._get_lock(name)
        async with lock:
            return await asyncio.to_thread(self._atomic_read_drain, name)

    def _atomic_read_drain(self, name: str) -> list[dict]:
        path = self.dir / f"{name}.jsonl"
        if not path.exists():
            return []
        text = path.read_text().strip()
        if not text:
            return []
        # Drain immediately after read -- under the same lock
        path.write_text("")
        msgs = []
        for line in text.splitlines():
            if line.strip():
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return msgs

    # ------------------------------------------------------------------
    async def broadcast(
        self,
        sender: str,
        content: str,
        recipients: list[str],
    ) -> str:
        """Send the same message to all recipients concurrently."""
        tasks = [
            self.send(sender, name, content, "broadcast")
            for name in recipients
            if name != sender
        ]
        await asyncio.gather(*tasks)
        return f"Broadcast to {len(tasks)} teammates"


# Singleton
MESSAGE_BUS = MessageBus()
