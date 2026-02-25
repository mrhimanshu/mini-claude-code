"""JSONL-based message bus for inter-agent communication (s09)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mini_claude_code.config import INBOX_DIR


class MessageBus:
    """Append-only JSONL inbox per agent.  Drain-on-read semantics."""

    def __init__(self, inbox_dir: Path | None = None) -> None:
        self.dir = inbox_dir or INBOX_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Append a message to *to*'s inbox."""
        msg: dict[str, Any] = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        inbox = self.dir / f"{to}.jsonl"
        with open(inbox, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    # ------------------------------------------------------------------
    def read_inbox(self, name: str) -> list[dict]:
        """Read and drain all messages from *name*'s inbox."""
        path = self.dir / f"{name}.jsonl"
        if not path.exists():
            return []
        text = path.read_text().strip()
        if not text:
            return []
        msgs = []
        for line in text.splitlines():
            if line.strip():
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        # Drain
        path.write_text("")
        return msgs

    # ------------------------------------------------------------------
    def broadcast(
        self,
        sender: str,
        content: str,
        recipients: list[str],
    ) -> str:
        """Send the same message to all recipients (except sender)."""
        count = 0
        for name in recipients:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


# Singleton
MESSAGE_BUS = MessageBus()
