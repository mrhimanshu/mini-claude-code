"""Human-in-the-loop approval for file modifications.

Shows a colored unified diff in the terminal and prompts the user to
accept or reject the change before it is written to disk.

The spinner (if running) is paused while the diff is displayed and
resumed after the user responds.
"""

from __future__ import annotations

import asyncio
import difflib
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from mini_claude_code.config import REQUIRE_APPROVAL

if TYPE_CHECKING:
    pass

console = Console()

# Module-level spinner reference — set by main.py at startup so the
# approval flow can pause/resume the animated spinner.
_spinner: object | None = None


def set_spinner(spinner: object) -> None:
    """Register the AsyncSpinner instance used by the REPL."""
    global _spinner
    _spinner = spinner


async def _stop_spinner() -> None:
    if _spinner is not None and getattr(_spinner, "running", False):
        await _spinner.stop()  # type: ignore[union-attr]


def _start_spinner() -> None:
    if _spinner is not None:
        _spinner.start("Running tools...", "1;36")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def request_approval(
    path: str,
    old_content: str,
    new_content: str,
    *,
    operation: str = "edit",
) -> bool:
    """Show a diff and ask the user to approve.

    Returns ``True`` if the change is approved, ``False`` if rejected.
    When ``REQUIRE_APPROVAL`` is disabled in config, always returns True.
    """
    if not REQUIRE_APPROVAL:
        return True

    await _stop_spinner()

    # --- build unified diff ---
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    # Ensure files end with newline for clean diff output
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )

    if not diff_lines:
        # No actual changes
        _start_spinner()
        return True

    diff_text = "".join(diff_lines)

    # --- display ---
    op_label = (
        "EDIT"
        if operation == "edit"
        else "NEW FILE"
        if operation == "create"
        else "WRITE"
    )
    border = "yellow" if operation == "edit" else "green"

    console.print()
    console.print(
        Panel(
            Syntax(diff_text, "diff", theme="monokai", line_numbers=False),
            title=f"[bold]{op_label}[/bold]: {path}",
            border_style=border,
            padding=(0, 1),
        )
    )

    # --- prompt ---
    prompt_text = Text.assemble(
        ("  Apply this change? ", "bold"),
        ("(y)es ", "green"),
        ("/ ", "dim"),
        ("(n)o ", "red"),
        (": ", "bold"),
    )
    console.print(prompt_text, end="")

    response = await asyncio.to_thread(input)
    approved = response.strip().lower() in ("y", "yes", "")

    if approved:
        console.print("  [green]Change accepted.[/green]")
    else:
        console.print("  [yellow]Change rejected.[/yellow]")

    console.print()
    _start_spinner()
    return approved
