"""Async interactive CLI REPL for Mini Claude Code.

Uses prompt_toolkit's prompt_async for non-blocking input,
LangGraph's astream for async streaming, Rich for formatting,
and real-time token streaming with an animated thinking spinner.

Supports two modes switchable via Tab:
  - Build Mode: full agent with tools (default)
  - Plan Mode:  structured plan generation, sharing, and collaborative approval
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sys
import traceback

from dotenv import load_dotenv

load_dotenv()

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from mini_claude_code.agent.graph import build_agent_graph, build_plan_graph
from mini_claude_code.agent.state import AgentState
from mini_claude_code.config import MODEL_NAME, PLAN_APPROVAL_TIMEOUT, WORKDIR
from mini_claude_code.plan.manager import PLAN_MANAGER, Annotation, Plan
from mini_claude_code.plan.server import PLAN_SERVER
from mini_claude_code.team.bus import MESSAGE_BUS
from mini_claude_code.team.manager import TEAMMATE_MANAGER
from mini_claude_code.tools.background import BG_MANAGER
from mini_claude_code.tools.task_board import TASK_MANAGER
from mini_claude_code.tools.todo import TODO_MANAGER

console = Console()


# ---------------------------------------------------------------------------
# Mode state (module-level so slash commands + keybindings can access it)
# ---------------------------------------------------------------------------

_current_mode: str = "build"  # "build" or "plan"


def get_mode() -> str:
    return _current_mode


def set_mode(mode: str) -> None:
    global _current_mode
    _current_mode = mode


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

    When ``silent=True`` tokens are buffered but **not** written to stdout.
    This is used in Plan Mode so the raw markdown is never shown; the caller
    renders the buffered text with Rich Markdown after generation completes.
    """

    def __init__(self, spinner: AsyncSpinner, *, silent: bool = False) -> None:
        super().__init__()
        self.spinner = spinner
        self.buffer: str = ""
        self.streaming: bool = False
        self._first_token: bool = True
        self.silent: bool = silent

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
            if not self.silent:
                await self.spinner.stop()
                # Blank line for visual separation after the spinner
                sys.stdout.write("\n")
                sys.stdout.flush()
        self.streaming = True
        self.buffer += text
        if not self.silent:
            sys.stdout.write(text)
            sys.stdout.flush()

    # -- called when the full LLM response is ready -----------------------

    async def on_llm_end(self, *_args, **_kwargs) -> None:  # type: ignore[override]
        if self.streaming and self.buffer and not self.silent:
            # End the streamed block with a blank line
            sys.stdout.write("\n")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Slash commands (async where needed)
# ---------------------------------------------------------------------------


async def handle_slash_command(cmd: str) -> str | None:
    """Handle slash commands. Returns a string signal or None.

    Return values:
        "compact"  - trigger compaction on next turn
        "approve"  - approve current plan locally
        "reject"   - reject current plan locally
        None       - command handled, no special action
    """
    parts = cmd.strip().split(None, 1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/quit", "/exit", "/q"):
        # Stop plan server if running
        if PLAN_SERVER.is_running:
            await PLAN_SERVER.stop()
        console.print("[dim]Goodbye![/dim]")
        sys.exit(0)

    elif command == "/help":
        console.print(
            Panel(
                "/help                - Show this help\n"
                "/quit                - Exit the REPL\n"
                "/mode                - Toggle Build/Plan mode (or press Tab)\n"
                "/approve             - Approve the current plan locally\n"
                "/reject [msg]        - Reject and abandon the plan\n"
                "/request-changes [msg] - Request changes (plan stays open for editing)\n"
                "/share               - Show the plan sharing URL\n"
                "/plan         - Display the current plan\n"
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

    elif command == "/mode":
        new_mode = "plan" if get_mode() == "build" else "build"
        set_mode(new_mode)
        _print_mode_indicator()

    elif command == "/approve":
        if PLAN_MANAGER.current_plan is None:
            console.print(
                "[yellow]No plan to approve. Generate a plan in Plan Mode first.[/yellow]"
            )
        else:
            return "approve"

    elif command == "/reject":
        if PLAN_MANAGER.current_plan is None:
            console.print("[yellow]No plan to reject.[/yellow]")
        else:
            return f"reject:{arg}"

    elif command == "/request-changes":
        if PLAN_MANAGER.current_plan is None:
            console.print("[yellow]No plan to request changes on.[/yellow]")
        else:
            reason = arg or ""
            if reason:
                ann = Annotation(
                    user="local",
                    text=f"Change requested: {reason}",
                    range_start=0,
                    range_end=len(PLAN_MANAGER.current_plan.content),
                )
                await PLAN_MANAGER.add_annotation(ann)
            PLAN_MANAGER.current_plan.status = "changes_requested"
            console.print(
                f"[yellow]Changes requested.[/yellow]"
                + (f" Reason: {reason}" if reason else "")
            )
            console.print(
                "[dim]The plan remains open for editing. "
                "Use /approve when ready, or /reject to abandon.[/dim]"
            )

    elif command == "/share":
        if PLAN_SERVER.is_running:
            _print_share_url()
        else:
            console.print("[yellow]No plan is currently being shared.[/yellow]")

    elif command == "/plan":
        if PLAN_MANAGER.current_plan is not None:
            text = PLAN_MANAGER.render_plan_text()
            console.print(Markdown(text))
        else:
            console.print(
                "[dim]No plan generated yet. Switch to Plan Mode and enter a request.[/dim]"
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
        return "compact"

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

    return None


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _print_mode_indicator() -> None:
    """Print the current mode with styling."""
    mode = get_mode()
    if mode == "build":
        console.print(
            "[bold green]>> Build Mode[/bold green] [dim](tools enabled, full execution)[/dim]"
        )
    else:
        console.print(
            "[bold yellow]>> Plan Mode[/bold yellow] [dim](plan generation only, no execution)[/dim]"
        )


def _print_share_url() -> None:
    """Print the plan sharing URL in a highlighted panel."""
    url = PLAN_SERVER.share_url
    local = PLAN_SERVER.local_url
    lines = [f"[bold]Share URL:[/bold] {url}"]
    if url != local:
        lines.append(f"[dim]Local:     {local}[/dim]")
    lines.append("")
    lines.append(
        "[dim]Open in a browser to review, annotate, and approve the plan.[/dim]"
    )
    console.print(Panel("\n".join(lines), title="Plan Sharing", border_style="cyan"))


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
# Plan mode flow: generate → share → wait for approval → execute
# ---------------------------------------------------------------------------


async def run_plan_flow(
    user_input: str,
    all_messages: list,
    plan_graph,
    build_agent,
    spinner: AsyncSpinner,
    streamer: TokenStreamer,
    session: PromptSession,
) -> list:
    """Run the full plan mode flow:

    1. Generate plan via plan-mode LLM (streamed naturally to terminal)
    2. Store the content as a Plan object
    3. Start sharing server
    4. Wait for approval (via WebSocket or /approve command)
    5. On approval, execute the (possibly modified) plan in Build Mode

    Returns the updated all_messages list.
    """
    # --- Step 1: Generate the plan (streams to stdout via TokenStreamer) ---
    plan_messages = [HumanMessage(content=user_input)]
    state: AgentState = {
        "messages": plan_messages,
        "rounds_since_todo": 0,
        "should_compact": False,
        "iteration_count": 0,
    }

    # Use a silent streamer for plan mode — we buffer the raw markdown
    # and render it with Rich Markdown after generation completes, so the
    # terminal never shows raw markdown symbols like # ** ``` etc.
    plan_streamer = TokenStreamer(spinner, silent=True)
    spinner.start("Planning...", "1;33")
    config = {"callbacks": [plan_streamer]}

    try:
        event = None
        async for event in plan_graph.astream(
            state, stream_mode="values", config=config
        ):
            pass
        await spinner.stop()
    except Exception as e:
        await spinner.stop()
        console.print(f"[red]Error generating plan: {e}[/red]")
        return all_messages

    # Render the plan with Rich Markdown for proper terminal formatting
    plan_text = plan_streamer.buffer.strip()
    if not plan_text:
        console.print("[red]No plan generated. Try rephrasing your request.[/red]")
        return all_messages

    # Display the plan with proper Rich Markdown formatting
    console.print()
    console.print(Markdown(plan_text))

    # --- Step 2: Create Plan object from the raw text ---
    plan = Plan(
        original_content=plan_text,
        content=plan_text,
        original_prompt=user_input,
        status="draft",
    )
    await PLAN_MANAGER.set_plan(plan)

    # Separator after the rendered plan
    console.print("[dim]" + "─" * 60 + "[/dim]")

    # --- Step 3: Start sharing server ---
    try:
        url = await PLAN_SERVER.start()
        plan.status = "shared"
        _print_share_url()
    except Exception as e:
        console.print(f"[yellow]Could not start plan server: {e}[/yellow]")
        console.print("[dim]You can still approve locally with /approve[/dim]")

    # --- Step 4: Wait for approval ---
    console.print(
        "\n[bold]Waiting for plan approval from all reviewers...[/bold] "
        "[dim](type /approve, /reject, or approve via the web UI)[/dim]"
    )

    # Register a callback so approval progress is shown in the terminal
    async def _on_approval_progress(user: str, status: dict) -> None:
        count = status.get("count", 0)
        total = status.get("total", 0)
        if not status.get("all_approved"):
            console.print(
                f"  [green]{user}[/green] approved the plan "
                f"[dim]({count}/{total})[/dim]"
            )

    PLAN_MANAGER.register_approval_progress_callback(_on_approval_progress)
    try:
        result = await _wait_for_plan_approval(session, spinner)
    finally:
        PLAN_MANAGER.unregister_approval_progress_callback(_on_approval_progress)

    if result == "approved":
        approved_plan = PLAN_MANAGER.current_plan
        if approved_plan and approved_plan.approved_by:
            approvers = ", ".join(approved_plan.approved_by)
            console.print(
                f"[bold green]Plan approved by all reviewers![/bold green] "
                f"[dim]({approvers})[/dim] Executing...\n"
            )
        else:
            console.print("[bold green]Plan approved![/bold green] Executing...\n")

        # --- Step 5: Execute the approved plan in Build Mode ---
        if approved_plan:
            approved_plan.status = "executing"
            execution_prompt = _build_execution_prompt(approved_plan)
            all_messages.append(HumanMessage(content=execution_prompt))

            exec_state: AgentState = {
                "messages": all_messages,
                "rounds_since_todo": 0,
                "should_compact": False,
                "iteration_count": 0,
            }

            spinner.start("Executing plan...")
            config = {"callbacks": [streamer]}

            try:
                event = None
                prev_len = len(all_messages)

                async for event in build_agent.astream(
                    exec_state, stream_mode="values", config=config
                ):
                    messages = event.get("messages", [])
                    if not messages:
                        continue

                    new_msgs = messages[prev_len:]
                    had_tool_results = False

                    for msg in new_msgs:
                        if isinstance(msg, AIMessage):
                            if msg.tool_calls:
                                await spinner.stop()
                                for tc in msg.tool_calls:
                                    display_tool_call(tc)
                        elif isinstance(msg, ToolMessage):
                            if not had_tool_results:
                                await spinner.stop()
                                had_tool_results = True
                            display_tool_result(msg)

                    if had_tool_results:
                        spinner.start("Thinking...")
                    elif (
                        new_msgs
                        and isinstance(new_msgs[-1], AIMessage)
                        and new_msgs[-1].tool_calls
                    ):
                        spinner.start("Running tools...", "1;36")

                    prev_len = len(messages)

                await spinner.stop()

                if event:
                    all_messages = list(event.get("messages", all_messages))

            except KeyboardInterrupt:
                await spinner.stop()
                console.print("\n[yellow]Plan execution interrupted.[/yellow]")
                all_messages.append(
                    AIMessage(content="(plan execution interrupted by user)")
                )
            except Exception as e:
                await spinner.stop()
                console.print(f"\n[red]Error during plan execution: {e}[/red]")
                console.print(f"[dim]{traceback.format_exc()}[/dim]")

    elif result == "rejected":
        reason = ""
        if PLAN_MANAGER.current_plan:
            reason = PLAN_MANAGER.current_plan.rejection_reason
        console.print(
            f"[yellow]Plan rejected.[/yellow]"
            + (f" Reason: {reason}" if reason else "")
        )
        console.print("[dim]Modify your request and try again in Plan Mode.[/dim]")

    elif result == "timeout":
        console.print("[yellow]Plan approval timed out.[/yellow]")

    # Stop the plan server
    if PLAN_SERVER.is_running:
        await PLAN_SERVER.stop()

    return all_messages


async def _wait_for_plan_approval(
    session: PromptSession,
    spinner: AsyncSpinner,
) -> str:
    """Concurrently wait for approval from either:
    - The web UI (via PlanManager's asyncio.Event)
    - Local CLI input (/approve or /reject slash commands)

    Returns: "approved" | "rejected" | "timeout"
    """

    async def _poll_cli_approval() -> str:
        """Listen for /approve or /reject from CLI."""
        while True:
            try:
                user_input = await session.prompt_async(HTML("<b>[approval]</b> > "))
                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    signal = await handle_slash_command(user_input)
                    if signal == "approve":
                        fully = await PLAN_MANAGER.record_approval("local")
                        if fully:
                            return "approved"
                        status = PLAN_MANAGER.get_approval_status()
                        console.print(
                            f"[green]You approved.[/green] "
                            f"[dim]({status['count']}/{status['total']} "
                            f"approved — waiting for others)[/dim]"
                        )
                    elif signal and signal.startswith("reject:"):
                        reason = signal[7:]
                        await PLAN_MANAGER.reject(reason=reason, user="local")
                        return "rejected"
                    # Other slash commands handled but don't end the wait
                else:
                    console.print(
                        "[dim]Type /approve to approve, /reject to reject, "
                        "or approve via the web UI.[/dim]"
                    )
            except (EOFError, KeyboardInterrupt):
                return "rejected"

    # Race: CLI input vs WebSocket approval vs timeout
    cli_task = asyncio.create_task(_poll_cli_approval())
    ws_task = asyncio.create_task(
        PLAN_MANAGER.wait_for_approval(timeout=PLAN_APPROVAL_TIMEOUT)
    )

    done, pending = await asyncio.wait(
        {cli_task, ws_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    for task in done:
        return task.result()

    return "timeout"


def _build_execution_prompt(plan: Plan) -> str:
    """Build a prompt for the Build Mode agent from an approved plan.

    Uses the final edited plan content only — no annotations, no reviewer
    markers, no tracking metadata.  Just the clean approved text.
    """
    clean_content = PLAN_MANAGER.get_clean_content()

    return (
        "Execute the following approved plan. It was collaboratively reviewed "
        "and edited by the team before approval.\n\n"
        f"Original request: {plan.original_prompt}\n\n"
        "--- APPROVED PLAN ---\n\n"
        f"{clean_content}\n\n"
        "--- END PLAN ---\n\n"
        "Implement the plan step by step. Use tools to make the changes."
    )


# ---------------------------------------------------------------------------
# Async main REPL
# ---------------------------------------------------------------------------


async def async_main() -> None:
    console.print(
        Panel(
            f"[bold]Mini Claude Code[/bold] (async)\n"
            f"Model: {MODEL_NAME}\n"
            f"Workspace: {WORKDIR}\n"
            f"Type /help for commands, /quit to exit\n"
            f"Press [bold]Tab[/bold] to switch between Build/Plan mode",
            border_style="blue",
        )
    )

    # Purge stale shutdown/error members from previous runs
    stale = await TEAMMATE_MANAGER.clear_stale()
    if stale:
        console.print(f"[dim]Cleaned {stale} stale teammate(s) from previous run[/dim]")

    # Build both agent graphs
    build_agent = build_agent_graph()
    plan_graph = build_plan_graph()

    # Setup key bindings for mode switching
    kb = KeyBindings()

    @kb.add("tab")
    def _toggle_mode(event) -> None:
        """Toggle between Build and Plan mode."""
        new_mode = "plan" if get_mode() == "build" else "build"
        set_mode(new_mode)
        # Clear current input buffer and re-render
        event.app.invalidate()

    def _get_toolbar() -> HTML:
        mode = get_mode()
        if mode == "build":
            return HTML(
                '<b style="bg:ansigreen fg:ansiblack"> BUILD MODE </b> '
                '<style fg="ansigray">Tools enabled | Press Tab to switch to Plan Mode</style>'
            )
        else:
            return HTML(
                '<b style="bg:ansiyellow fg:ansiblack"> PLAN MODE </b> '
                '<style fg="ansigray">Plan only, no execution | Press Tab to switch to Build Mode</style>'
            )

    def _get_prompt() -> HTML:
        mode = get_mode()
        if mode == "build":
            return HTML("<b style='fg:ansigreen'>build</b> <b>&gt;</b> ")
        else:
            return HTML("<b style='fg:ansiyellow'>plan</b> <b>&gt;</b> ")

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        key_bindings=kb,
        bottom_toolbar=_get_toolbar,
    )

    all_messages: list = []
    rounds_since_todo: int = 0
    force_compact: bool = False

    spinner = AsyncSpinner()
    streamer = TokenStreamer(spinner)

    _print_mode_indicator()

    while True:
        try:
            user_input = await session.prompt_async(_get_prompt)
            user_input = user_input.strip()
        except (EOFError, KeyboardInterrupt):
            if PLAN_SERVER.is_running:
                await PLAN_SERVER.stop()
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            signal = await handle_slash_command(user_input)
            if signal == "compact":
                force_compact = True
                console.print("[dim]Compaction queued for next turn.[/dim]")
            # /approve and /reject are only meaningful during plan approval wait
            continue

        # Route based on current mode
        if get_mode() == "plan":
            # ---- Plan Mode Flow ----
            all_messages = await run_plan_flow(
                user_input=user_input,
                all_messages=all_messages,
                plan_graph=plan_graph,
                build_agent=build_agent,
                spinner=spinner,
                streamer=streamer,
                session=session,
            )
            continue

        # ---- Build Mode (default) ----
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

            async for event in build_agent.astream(
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
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def main() -> None:
    """Entry point -- runs the async REPL."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
