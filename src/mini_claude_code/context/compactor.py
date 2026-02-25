"""Three-layer context compaction pipeline (s06) + identity re-injection (s11)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)

from mini_claude_code.config import (
    KEEP_RECENT_TOOL_RESULTS,
    MODEL_NAME,
    TOKEN_THRESHOLD,
    TRANSCRIPTS_DIR,
    ANTHROPIC_API_KEY,
)


# ---------------------------------------------------------------------------
# Token estimation (rough heuristic: chars / 4)
# ---------------------------------------------------------------------------


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    """Rough token estimate for a list of messages."""
    total = 0
    for msg in messages:
        if isinstance(msg.content, str):
            total += len(msg.content) // 4
        elif isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, dict):
                    total += len(json.dumps(part)) // 4
                else:
                    total += len(str(part)) // 4
    return total


# ---------------------------------------------------------------------------
# Layer 1: micro_compact -- replace old tool results with placeholders
# ---------------------------------------------------------------------------


def micro_compact(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Replace tool result messages older than the last KEEP_RECENT with placeholders.

    Returns a new list of update messages (RemoveMessage + replacement ToolMessage).
    """
    tool_indices: list[int] = []
    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            tool_indices.append(i)

    if len(tool_indices) <= KEEP_RECENT_TOOL_RESULTS:
        return []

    to_replace = tool_indices[:-KEEP_RECENT_TOOL_RESULTS]
    updates: list[BaseMessage] = []

    for idx in to_replace:
        msg = messages[idx]
        if isinstance(msg, ToolMessage) and len(str(msg.content)) > 100:
            updates.append(RemoveMessage(id=msg.id or ""))

    return updates


# ---------------------------------------------------------------------------
# Layer 2: auto_compact -- summarize when tokens exceed threshold
# ---------------------------------------------------------------------------


def auto_compact(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Summarize the entire conversation using the LLM, save transcript.

    Returns the list of message updates to apply (removals + summary).
    """
    from langchain_anthropic import ChatAnthropic

    # Save transcript first
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    transcript_path = TRANSCRIPTS_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(
                json.dumps({"type": msg.type, "content": str(msg.content)[:2000]})
                + "\n"
            )

    # Build a summary request
    conversation_text = []
    for msg in messages:
        content = str(msg.content)[:1000]
        conversation_text.append(f"[{msg.type}] {content}")
    conversation_str = "\n".join(conversation_text)[:80_000]

    llm = ChatAnthropic(
        model_name=MODEL_NAME,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=2000,
        timeout=60,
        stop=None,
    )
    summary_response = llm.invoke(
        f"Summarize this conversation for continuity. "
        f"Focus on: what was accomplished, what is in progress, "
        f"key decisions, file paths mentioned, current task state.\n\n"
        f"{conversation_str}"
    )
    summary = summary_response.content

    # Build updates: remove all old messages, add summary
    updates: list[BaseMessage] = []
    for msg in messages:
        if msg.id:
            updates.append(RemoveMessage(id=msg.id))

    updates.append(HumanMessage(content=f"[Context Compressed]\n\n{summary}"))
    updates.append(
        AIMessage(content="Understood. I have the context summary. Continuing work.")
    )

    return updates


# ---------------------------------------------------------------------------
# Check if compaction is needed
# ---------------------------------------------------------------------------


def needs_compaction(messages: Sequence[BaseMessage]) -> bool:
    """Return True if estimated tokens exceed the threshold."""
    return estimate_tokens(messages) > TOKEN_THRESHOLD


# ---------------------------------------------------------------------------
# Identity re-injection (s11)
# ---------------------------------------------------------------------------


def make_identity_block(
    name: str, role: str, team_name: str = "default"
) -> HumanMessage:
    """Create an identity injection message for after compression."""
    return HumanMessage(
        content=(
            f"<identity>You are '{name}', role: {role}, team: {team_name}. "
            f"Continue your work.</identity>"
        )
    )
