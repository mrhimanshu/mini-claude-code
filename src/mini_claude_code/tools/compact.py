"""Manual compact tool (s06 layer 3)."""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def compact() -> str:
    """Manually trigger context compaction.

    Compresses the conversation history into a summary to free up
    context window space.  Useful when the conversation is getting long.

    Returns:
        Confirmation that compaction was requested.
    """
    # The actual compaction logic is handled by the preprocess node
    # when it sees this tool was called.  We just return a signal.
    return "[compact-requested] Context compaction will occur on the next turn."
