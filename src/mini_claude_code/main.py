"""Async interactive CLI REPL for Mini Claude Code.

Uses prompt_toolkit's prompt_async for non-blocking input,
LangGraph's astream for async streaming, Rich for formatting,
and real-time token streaming with an animated thinking spinner.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sys

from dotenv import load_dotenv

load_dotenv()

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

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
# Animated async spinner
# ---------------------------------------------------------------------------

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class AsyncSpinner:
    """Animated braille-dot spinner that runs as a background asyncio task.

    Uses raw ANSI escapes to avoid conflicting with Rich Live.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _run(self, text: str, color: str) -> None:
        frames = itertools.cycle(_SPINNER_FRAMES)
        reset = "\033[0m"
        try:
            while not self._stop.is_set():
                frame = next(frames)
                sys.stdout.write(f"\r\033[K  \033[{color}m{frame} {text}{reset}")
                sys.stdout.flush()
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop.wait()), timeout=0.08
                    )
                    break
                except asyncio.TimeoutError:
                    pass
        finally:
            # Clear the spinner line
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def start(self, text: str = "Thinking...", color: str = "1;34") -> None:
        """Start the spinner with *text* in ANSI *color* code."""
        self._stop.clear()
        self._task = asyncio.create_task(self._run(text, color))

    async def stop(self) -> None:
        """Stop the spinner (idempotent)."""
        if self._task is not None and not self._task.done():
            self._stop.set()
            await self._task
        self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()


# ---------------------------------------------------------------------------
# Streaming callback handler
# ---------------------------------------------------------------------------


class TokenStreamer(AsyncCallbackHandler):
    """Captures streaming LLM tokens and writes them to stdout in real-time.

    Integrates with AsyncSpinner: the spinner is stopped on the first token
    so the response text cleanly replaces the spinner line.
    """

    def __init__(self, spinner: AsyncSpinner) -> None:
        super().__init__()
        self.spinner = spinner
        self.buffer: str = ""
        self.streaming: bool = False
        self._first_token: bool = True

    # -- called at the start of each LLM invocation -----------------------

    async def on_chat_model_start(self, *_args, **_kwargs) -> None:  # type: ignore[override]
        """Reset per-call state so the streamer is fresh for each LLM turn."""
        self.buffer = ""
        self.streaming = False
        self._first_token = True

    # -- called for every text token --------------------------------------

    async def on_llm_new_token(self, token, **_kwargs) -> None:  # type: ignore[override]
        # With bound tools, ChatAnthropic sends content-block lists
        # e.g. [{'text': 'hello', 'type': 'text', 'index': 0}]
        if isinstance(token, list):
            text = "".join(
                block.get("text", "") for block in token if isinstance(block, dict)
            )
        else:
            text = str(token)

        if not text:
            return
        if self._first_token:
            self._first_token = False
            await self.spinner.stop()
            # Blank line for visual separation after the spinner
            sys.stdout.write("\n")
            sys.stdout.flush()
        self.streaming = True
        self.buffer += text
        sys.stdout.write(text)
        sys.stdout.flush()

    # -- called when the full LLM response is ready -----------------------

    async def on_llm_end(self, *_args, **_kwargs) -> None:  # type: ignore[override]
        if self.streaming and self.buffer:
            # End the streamed block with a blank line
            sys.stdout.write("\n")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Slash commands (async where needed)
# ---------------------------------------------------------------------------


async def handle_slash_command(cmd: str) -> bool:
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
                "/model        - Show current model\n"
                "/clear        - Reset .tasks and .team state",
                title="Slash Commands",
                border_style="blue",
            )
        )

    elif command == "/todos":
        rendered = await TODO_MANAGER.render()
        console.print(Panel(rendered, title="Todos", border_style="yellow"))

    elif command == "/tasks":
        rendered = await TASK_MANAGER.list_all()
        console.print(Panel(rendered, title="Task Board", border_style="green"))

    elif command == "/team":
        rendered = await TEAMMATE_MANAGER.list_members()
        console.print(Panel(rendered, title="Team", border_style="cyan"))

    elif command == "/inbox":
        msgs = await MESSAGE_BUS.read_inbox("lead")
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
        tasks = await BG_MANAGER.list_tasks()
        if not tasks:
            console.print("[dim]No background tasks[/dim]")
        else:
            lines = []
            for tid, t in tasks.items():
                lines.append(f"[{tid}] {t['status']}: {t['command']}")
            console.print(
                Panel("\n".join(lines), title="Background Tasks", border_style="red")
            )

    elif command == "/compact":
        console.print("[dim]Compaction will occur on the next agent turn.[/dim]")
        return True

    elif command == "/model":
        console.print(f"[dim]Model: {MODEL_NAME}[/dim]")

    elif command == "/clear":
        task_result = await TASK_MANAGER.clear_all()
        team_result = await TEAMMATE_MANAGER.clear_all()
        console.print(f"[dim]{task_result}[/dim]")
        console.print(f"[dim]{team_result}[/dim]")

    else:
        console.print(
            f"[red]Unknown command: {command}[/red]. Type /help for available commands."
        )

    return True


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def display_tool_call(tc: dict) -> None:
    name = tc.get("name", "?")
    args = tc.get("args", {})
    args_str = json.dumps(args, indent=2)
    if len(args_str) > 300:
        args_str = args_str[:300] + "..."
    console.print(f"  [bold cyan]⚡ {name}[/bold cyan]")
    console.print(f"  [dim]{args_str}[/dim]")


def display_tool_result(msg: ToolMessage) -> None:
    content = str(msg.content)
    if len(content) > 500:
        content = content[:500] + "..."
    console.print(f"  [dim green]↳ {content}[/dim green]")


# ---------------------------------------------------------------------------
# Async main REPL
# ---------------------------------------------------------------------------


async def async_main() -> None:
    console.print(
        Panel(
            f"[bold]Mini Claude Code[/bold] (async)\n"
            f"Model: {MODEL_NAME}\n"
            f"Workspace: {WORKDIR}\n"
            f"Type /help for commands, /quit to exit",
            border_style="blue",
        )
    )

    # Purge stale shutdown/error members from previous runs
    stale = await TEAMMATE_MANAGER.clear_stale()
    if stale:
        console.print(f"[dim]Cleaned {stale} stale teammate(s) from previous run[/dim]")

    agent = build_agent_graph()
    session: PromptSession = PromptSession(history=InMemoryHistory())

    all_messages: list = []
    rounds_since_todo: int = 0
    force_compact: bool = False

    spinner = AsyncSpinner()
    streamer = TokenStreamer(spinner)

    while True:
        try:
            user_input = await session.prompt_async("\n> ")
            user_input = user_input.strip()
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
                await handle_slash_command(user_input)
            continue

        # Add user message
        all_messages.append(HumanMessage(content=user_input))

        state: AgentState = {
            "messages": all_messages,
            "rounds_since_todo": rounds_since_todo,
            "should_compact": force_compact,
            "iteration_count": 0,
        }
        force_compact = False

        # Start the thinking spinner
        spinner.start("Thinking...")

        config = {"callbacks": [streamer]}

        try:
            event = None
            prev_len = len(all_messages)

            async for event in agent.astream(
                state, stream_mode="values", config=config
            ):
                messages = event.get("messages", [])
                if not messages:
                    continue

                new_msgs = messages[prev_len:]
                had_tool_results = False

                for msg in new_msgs:
                    if isinstance(msg, AIMessage):
                        # Text content was already streamed to stdout by
                        # the TokenStreamer callback — no need to re-display.
                        if msg.tool_calls:
                            # Stop spinner if LLM produced only tool_calls
                            # (no text tokens → spinner still running)
                            await spinner.stop()
                            for tc in msg.tool_calls:
                                display_tool_call(tc)

                    elif isinstance(msg, ToolMessage):
                        if not had_tool_results:
                            await spinner.stop()
                            had_tool_results = True
                        display_tool_result(msg)

                # Decide which spinner to show for the next phase
                if had_tool_results:
                    spinner.start("Thinking...")
                elif (
                    new_msgs
                    and isinstance(new_msgs[-1], AIMessage)
                    and new_msgs[-1].tool_calls
                ):
                    spinner.start("Running tools...", "1;36")

                prev_len = len(messages)

            # Make sure the spinner is cleaned up
            await spinner.stop()

            # Update persistent state from final event
            if event:
                all_messages = list(event.get("messages", all_messages))
                rounds_since_todo = event.get("rounds_since_todo", rounds_since_todo)

        except KeyboardInterrupt:
            await spinner.stop()
            console.print("\n[yellow]Interrupted.[/yellow]")
            all_messages.append(AIMessage(content="(interrupted by user)"))
        except Exception as e:
            await spinner.stop()
            console.print(f"\n[red]Error: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def main() -> None:
    """Entry point -- runs the async REPL."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
