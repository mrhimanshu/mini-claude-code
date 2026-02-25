"""Interactive CLI REPL for Mini Claude Code."""

from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from mini_claude_code.agent.graph import build_agent_graph
from mini_claude_code.agent.state import AgentState
from mini_claude_code.config import MODEL_NAME, WORKDIR
from mini_claude_code.team.bus import MESSAGE_BUS
from mini_claude_code.team.manager import TEAMMATE_MANAGER
from mini_claude_code.tools.background import BG_MANAGER
from mini_claude_code.tools.task_board import TASK_MANAGER
from mini_claude_code.tools.todo import TODO_MANAGER

console = Console()


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def handle_slash_command(cmd: str) -> bool:
    """Handle slash commands. Returns True if handled."""
    parts = cmd.strip().split(None, 1)
    command = parts[0].lower()

    if command in ("/quit", "/exit", "/q"):
        console.print("[dim]Goodbye![/dim]")
        sys.exit(0)

    elif command == "/help":
        console.print(
            Panel(
                "/help         - Show this help\n"
                "/quit         - Exit the REPL\n"
                "/todos        - Show current todo list\n"
                "/tasks        - Show task board\n"
                "/team         - Show teammate roster\n"
                "/inbox        - Check lead inbox\n"
                "/bg           - Show background tasks\n"
                "/compact      - Trigger manual compaction\n"
                "/model        - Show current model",
                title="Slash Commands",
                border_style="blue",
            )
        )

    elif command == "/todos":
        rendered = TODO_MANAGER.render()
        console.print(Panel(rendered, title="Todos", border_style="yellow"))

    elif command == "/tasks":
        rendered = TASK_MANAGER.list_all()
        console.print(Panel(rendered, title="Task Board", border_style="green"))

    elif command == "/team":
        rendered = TEAMMATE_MANAGER.list_members()
        console.print(Panel(rendered, title="Team", border_style="cyan"))

    elif command == "/inbox":
        msgs = MESSAGE_BUS.read_inbox("lead")
        if msgs:
            console.print(
                Panel(
                    json.dumps(msgs, indent=2),
                    title="Lead Inbox",
                    border_style="magenta",
                )
            )
        else:
            console.print("[dim]No messages in inbox[/dim]")

    elif command == "/bg":
        if not BG_MANAGER.tasks:
            console.print("[dim]No background tasks[/dim]")
        else:
            lines = []
            for tid, t in BG_MANAGER.tasks.items():
                lines.append(f"[{tid}] {t['status']}: {t['command']}")
            console.print(
                Panel("\n".join(lines), title="Background Tasks", border_style="red")
            )

    elif command == "/compact":
        console.print("[dim]Compaction will occur on the next agent turn.[/dim]")
        return True  # signal to inject compact

    elif command == "/model":
        console.print(f"[dim]Model: {MODEL_NAME}[/dim]")

    else:
        console.print(
            f"[red]Unknown command: {command}[/red]. Type /help for available commands."
        )

    return True


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def display_tool_call(tc: dict) -> None:
    """Display a tool call in a compact format."""
    name = tc.get("name", "?")
    args = tc.get("args", {})
    # Truncate long args for display
    args_str = json.dumps(args, indent=2)
    if len(args_str) > 300:
        args_str = args_str[:300] + "..."
    console.print(f"  [bold cyan]tool:[/bold cyan] {name}")
    console.print(f"  [dim]{args_str}[/dim]")


def display_tool_result(msg: ToolMessage) -> None:
    """Display a tool result."""
    content = str(msg.content)
    if len(content) > 500:
        content = content[:500] + "..."
    console.print(f"  [dim green]{content}[/dim green]")


def display_response(msg: AIMessage) -> None:
    """Display the AI's text response."""
    if msg.content:
        text = str(msg.content)
        if text.strip():
            console.print()
            try:
                console.print(Markdown(text))
            except Exception:
                console.print(text)
            console.print()


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------


def main() -> None:
    console.print(
        Panel(
            f"[bold]Mini Claude Code[/bold]\n"
            f"Model: {MODEL_NAME}\n"
            f"Workspace: {WORKDIR}\n"
            f"Type /help for commands, /quit to exit",
            border_style="blue",
        )
    )

    agent = build_agent_graph()
    session = PromptSession(history=InMemoryHistory())

    # Persistent state across turns
    all_messages: list = []
    rounds_since_todo: int = 0
    force_compact: bool = False

    while True:
        try:
            user_input = session.prompt("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            if user_input.strip().lower() == "/compact":
                force_compact = True
                console.print("[dim]Compaction queued for next turn.[/dim]")
            else:
                handle_slash_command(user_input)
            continue

        # Add user message
        all_messages.append(HumanMessage(content=user_input))

        # Build initial state
        state: AgentState = {
            "messages": all_messages,
            "rounds_since_todo": rounds_since_todo,
            "should_compact": force_compact,
            "iteration_count": 0,
        }
        force_compact = False

        console.print("[dim]Thinking...[/dim]")

        try:
            # Stream events from the graph
            for event in agent.stream(state, stream_mode="values"):
                messages = event.get("messages", [])
                if not messages:
                    continue

                # Show new messages only
                new_start = len(all_messages)
                for msg in messages[new_start:]:
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                display_tool_call(tc)
                        else:
                            display_response(msg)
                    elif isinstance(msg, ToolMessage):
                        display_tool_result(msg)

            # Update persistent state from final event
            if event:
                all_messages = list(event.get("messages", all_messages))
                rounds_since_todo = event.get("rounds_since_todo", rounds_since_todo)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            # Add a note about interruption
            all_messages.append(AIMessage(content="(interrupted by user)"))
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")


if __name__ == "__main__":
    main()
