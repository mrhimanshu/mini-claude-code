"""Async TeammateManager: lifecycle management for persistent agent teammates (s09, s11).

Teammates run as asyncio.Task (not threads). All shared state is
protected by asyncio.Lock. Task claiming is atomic.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from mini_claude_code.config import (
    ANTHROPIC_API_KEY,
    IDLE_POLL_INTERVAL,
    IDLE_TIMEOUT,
    MAX_SUBAGENT_ITERATIONS,
    MODEL_NAME,
    WORKDIR,
    TEAM_DIR,
)
from mini_claude_code.context.compactor import make_identity_block
from mini_claude_code.team.bus import MESSAGE_BUS
from mini_claude_code.tools.task_board import TASK_MANAGER


class TeammateManager:
    """Manages named teammates, each running an async agent loop as an asyncio.Task."""

    def __init__(self, team_dir: Path | None = None) -> None:
        self.dir = team_dir or TEAM_DIR
        self.config_path = self.dir / "config.json"
        self._config: dict | None = None
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Config persistence (all under lock)
    # ------------------------------------------------------------------
    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _load_config_sync(self) -> dict:
        self._ensure_dir()
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save_config_sync(self, config: dict) -> None:
        self._ensure_dir()
        self.config_path.write_text(json.dumps(config, indent=2))

    async def _get_config(self) -> dict:
        """Get config (lazy load, under lock)."""
        if self._config is None:
            self._config = await asyncio.to_thread(self._load_config_sync)
        return self._config

    async def _save_config(self) -> None:
        if self._config is not None:
            await asyncio.to_thread(self._save_config_sync, self._config)

    def _find_member(self, config: dict, name: str) -> dict | None:
        for m in config["members"]:
            if m["name"] == name:
                return m
        return None

    async def _set_status(self, name: str, status: str) -> None:
        async with self._lock:
            config = await self._get_config()
            member = self._find_member(config, name)
            if member:
                member["status"] = status
                await self._save_config()

    # ------------------------------------------------------------------
    # Spawn (async)
    # ------------------------------------------------------------------
    async def spawn(self, name: str, role: str, prompt: str) -> str:
        async with self._lock:
            config = await self._get_config()
            member = self._find_member(config, name)
            if member:
                if member["status"] == "working":
                    return f"Error: '{name}' is already working"
                member["status"] = "working"
                member["role"] = role
            else:
                member = {"name": name, "role": role, "status": "working"}
                config["members"].append(member)
            await self._save_config()

        # Launch as asyncio task with a done-callback that logs crashes
        task = asyncio.create_task(
            self._teammate_loop(name, role, prompt),
            name=f"teammate-{name}",
        )

        def _on_done(t: asyncio.Task) -> None:
            exc = t.exception() if not t.cancelled() else None
            if exc:
                import sys

                print(
                    f"[team] teammate '{name}' crashed: {exc}",
                    file=sys.stderr,
                )

        task.add_done_callback(_on_done)
        self._tasks[name] = task
        return f"Spawned teammate '{name}' (role: {role})"

    # ------------------------------------------------------------------
    # Teammate agent loop (async)
    # ------------------------------------------------------------------
    async def _teammate_loop(self, name: str, role: str, prompt: str) -> None:
        from mini_claude_code.tools import get_child_tools

        tools = get_child_tools()
        llm = ChatAnthropic(
            model_name=MODEL_NAME,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=8192,
            timeout=120,
            stop=None,
        ).bind_tools(tools)

        tool_map = {t.name: t for t in tools}
        messages: list[BaseMessage] = [HumanMessage(content=prompt)]

        # Define _exec_tool ONCE (not inside the loop — avoids
        # re-creating the closure on every iteration).
        async def _exec_tool(tc: dict) -> ToolMessage:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as e:
                    result = f"Error: {e}"
            else:
                result = f"Unknown tool: {tc['name']}"
            return ToolMessage(content=str(result), tool_call_id=tc["id"])

        try:
            while True:
                # -- WORK PHASE --
                should_exit = False
                for _ in range(MAX_SUBAGENT_ITERATIONS):
                    # Check inbox
                    inbox = await MESSAGE_BUS.read_inbox(name)
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            req_id = msg.get("request_id", "")
                            from mini_claude_code.team.protocols import (
                                handle_shutdown_response,
                            )

                            await handle_shutdown_response(
                                req_id, True, "Shutting down as requested."
                            )
                            should_exit = True
                            break
                        messages.append(
                            HumanMessage(content=f"<inbox>{json.dumps(msg)}</inbox>")
                        )

                    if should_exit:
                        break

                    try:
                        response = await llm.ainvoke(messages)
                    except Exception as e:
                        messages.append(
                            HumanMessage(content=f"<error>LLM call failed: {e}</error>")
                        )
                        break

                    messages.append(response)

                    if not isinstance(response, AIMessage) or not response.tool_calls:
                        break

                    # Execute tool calls in parallel
                    tool_msgs = await asyncio.gather(
                        *[_exec_tool(tc) for tc in response.tool_calls]
                    )
                    messages.extend(tool_msgs)

                if should_exit:
                    return  # finally block handles status

                # -- IDLE PHASE (s11) --
                await self._set_status(name, "idle")
                resume = await self._idle_poll(name, messages)
                if not resume:
                    return  # finally block handles status
                await self._set_status(name, "working")

        except Exception:
            await self._set_status(name, "error")
            raise  # re-raise so the done-callback logs it
        finally:
            # Always mark shutdown unless already set to "error"
            async with self._lock:
                config = await self._get_config()
                member = self._find_member(config, name)
                if member and member["status"] != "error":
                    member["status"] = "shutdown"
                    await self._save_config()

    # ------------------------------------------------------------------
    # Idle polling (async, s11)
    # ------------------------------------------------------------------
    async def _idle_poll(self, name: str, messages: list[BaseMessage]) -> bool:
        polls = IDLE_TIMEOUT // IDLE_POLL_INTERVAL
        for _ in range(polls):
            await asyncio.sleep(IDLE_POLL_INTERVAL)

            # Check inbox
            inbox = await MESSAGE_BUS.read_inbox(name)
            if inbox:
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        req_id = msg.get("request_id", "")
                        from mini_claude_code.team.protocols import (
                            handle_shutdown_response,
                        )

                        await handle_shutdown_response(req_id, True, "Shutting down.")
                        return False
                    messages.append(
                        HumanMessage(content=f"<inbox>{json.dumps(msg)}</inbox>")
                    )
                return True

            # Scan task board for unclaimed tasks (atomic claim)
            unclaimed = await TASK_MANAGER.scan_unclaimed()
            if unclaimed:
                task = unclaimed[0]
                claimed = await TASK_MANAGER.claim_task(task["id"], name)
                if claimed:
                    messages.append(
                        HumanMessage(
                            content=f"<auto-claimed>Task #{task['id']}: {task['subject']}</auto-claimed>"
                        )
                    )
                    # Identity re-injection if context is short
                    if len(messages) <= 3:
                        async with self._lock:
                            config = await self._get_config()
                            member = self._find_member(config, name)
                        role = member["role"] if member else "agent"
                        messages.insert(0, make_identity_block(name, role))
                        messages.insert(
                            1, AIMessage(content=f"I am {name}. Continuing.")
                        )
                    return True

        return False  # timeout

    # ------------------------------------------------------------------
    # Cleanup (async)
    # ------------------------------------------------------------------
    async def clear_stale(self) -> int:
        """Remove members with status 'shutdown'/'error' that have no
        running asyncio.Task.  Also deletes their empty inbox files.
        Returns number of members removed.
        """
        async with self._lock:
            config = await self._get_config()
            alive = []
            removed = 0
            for m in config["members"]:
                name = m["name"]
                task = self._tasks.get(name)
                has_running_task = task is not None and not task.done()
                if m["status"] in ("shutdown", "error") and not has_running_task:
                    removed += 1
                    # Clean up inbox file
                    inbox_file = self.dir / "inbox" / f"{name}.jsonl"
                    if inbox_file.exists():
                        try:
                            inbox_file.unlink()
                        except OSError:
                            pass
                    self._tasks.pop(name, None)
                else:
                    alive.append(m)
            if removed:
                config["members"] = alive
                await self._save_config()
        return removed

    async def clear_all(self) -> str:
        """Cancel all running teammates and wipe team state.
        Used by /clear slash command.
        """
        async with self._lock:
            # Cancel running tasks
            for name, task in list(self._tasks.items()):
                if not task.done():
                    task.cancel()
            self._tasks.clear()
            # Wipe config
            self._config = {"team_name": "default", "members": []}
            await self._save_config()
            # Wipe inbox files
            inbox_dir = self.dir / "inbox"
            if inbox_dir.exists():
                for f in inbox_dir.glob("*.jsonl"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
        return "Team state cleared"

    # ------------------------------------------------------------------
    # Query (async)
    # ------------------------------------------------------------------
    async def list_members(self) -> str:
        async with self._lock:
            config = await self._get_config()
        if not config["members"]:
            return "(no teammates)"
        lines = []
        for m in config["members"]:
            lines.append(f"  {m['name']} (role: {m['role']}, status: {m['status']})")
        return "\n".join(lines)

    async def get_member_names(self) -> list[str]:
        async with self._lock:
            config = await self._get_config()
        return [m["name"] for m in config.get("members", [])]


# Singleton
TEAMMATE_MANAGER = TeammateManager()
