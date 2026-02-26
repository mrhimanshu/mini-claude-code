"""Async bash execution tool using asyncio subprocess (s01/s02)."""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR, BG_COMMAND_TIMEOUT


@tool
async def bash_tool(command: str, timeout: int | None = None) -> str:
    """Run a bash command in the workspace directory.

    Args:
        command: The shell command to execute.
        timeout: Optional timeout in seconds (default 300).

    Returns:
        Combined stdout + stderr output, truncated to 50 000 chars.
    """
    effective_timeout = timeout or BG_COMMAND_TIMEOUT
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKDIR),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: Command timed out after {effective_timeout}s"

        output = ((stdout or b"") + (stderr or b"")).decode(errors="replace").strip()
        if not output:
            return "(no output)"
        if len(output) > 50_000:
            return output[:50_000] + "\n\n... [truncated]"
        return output
    except Exception as e:
        return f"Error: {e}"
