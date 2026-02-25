"""Bash execution tool with timeout and output truncation (s01/s02)."""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool

from mini_claude_code.config import WORKDIR, BG_COMMAND_TIMEOUT


@tool
def bash_tool(command: str, timeout: int | None = None) -> str:
    """Run a bash command in the workspace directory.

    Args:
        command: The shell command to execute.
        timeout: Optional timeout in seconds (default 300).

    Returns:
        Combined stdout + stderr output, truncated to 50 000 chars.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKDIR),
            capture_output=True,
            text=True,
            timeout=timeout or BG_COMMAND_TIMEOUT,
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            return "(no output)"
        # Truncate very long outputs
        if len(output) > 50_000:
            return output[:50_000] + "\n\n... [truncated]"
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout or BG_COMMAND_TIMEOUT}s"
    except Exception as e:
        return f"Error: {e}"
