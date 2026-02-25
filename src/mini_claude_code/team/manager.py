"""TeammateManager: lifecycle management for persistent agent teammates (s09, s11)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

from mini_claude_code.config import (
    ANTHROPIC_API_KEY,
    IDLE_POLL_INTERVAL,
    IDLE_TIMEOUT,
    MAX_SUBAGENT_ITERATIONS,
    MODEL_NAME,
    TASKS_DIR,
    TEAM_DIR,
    WORKDIR,
)
from mini_claude_code.context.compactor import make_identity_block
from mini_claude_code.team.bus import MESSAGE_BUS


class TeammateManager:
    """Manages named teammates, each running an agent loop in a daemon thread."""

    def __init__(self, team_dir: Path | None = None) -> None:
        self.dir = team_dir or TEAM_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads: dict[str, threading.Thread] = {}

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------
    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find_member(self, name: str) -> dict | None:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _set_status(self, name: str, status: str) -> None:
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------
    def spawn(self, name: str, role: str, prompt: str) -> str:
        """Create or reactivate a teammate in a daemon thread."""
        member = self._find_member(name)
        if member:
            if member["status"] == "working":
                return f"Error: '{name}' is already working"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned teammate '{name}' (role: {role})"

    # ------------------------------------------------------------------
    # Teammate agent loop
    # ------------------------------------------------------------------
    def _teammate_loop(self, name: str, role: str, prompt: str) -> None:
        """Full agent loop for a teammate, with idle polling (s11)."""
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
        sys_prompt = (
            f"You are '{name}', role: {role}, working at {WORKDIR}.\n"
            f"You are a teammate agent. Complete your assigned work, then "
            f"signal completion. Stay focused on your task."
        )

        messages = [HumanMessage(content=prompt)]

        while True:
            # -- WORK PHASE --
            should_exit = False
            for _ in range(MAX_SUBAGENT_ITERATIONS):
                # Check inbox
                inbox = MESSAGE_BUS.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        # Auto-approve shutdown
                        req_id = msg.get("request_id", "")
                        from mini_claude_code.team.protocols import (
                            handle_shutdown_response,
                        )

                        handle_shutdown_response(
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
                    response = llm.invoke(
                        messages,
                        config={"configurable": {"system_message": sys_prompt}},
                    )
                except Exception as e:
                    messages.append(
                        HumanMessage(content=f"<error>LLM call failed: {e}</error>")
                    )
                    break

                messages.append(response)

                if not response.tool_calls:
                    break

                # Execute tool calls
                from langchain_core.messages import ToolMessage

                for tc in response.tool_calls:
                    tool_fn = tool_map.get(tc["name"])
                    if tool_fn:
                        try:
                            result = tool_fn.invoke(tc["args"])
                        except Exception as e:
                            result = f"Error: {e}"
                    else:
                        result = f"Unknown tool: {tc['name']}"
                    messages.append(
                        ToolMessage(content=str(result), tool_call_id=tc["id"])
                    )

            if should_exit:
                self._set_status(name, "shutdown")
                return

            # -- IDLE PHASE (s11) --
            self._set_status(name, "idle")
            resume = self._idle_poll(name, messages)
            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    # ------------------------------------------------------------------
    # Idle polling (s11)
    # ------------------------------------------------------------------
    def _idle_poll(self, name: str, messages: list) -> bool:
        """Poll inbox and task board. Returns True if work found."""
        polls = IDLE_TIMEOUT // IDLE_POLL_INTERVAL
        for _ in range(polls):
            time.sleep(IDLE_POLL_INTERVAL)

            # Check inbox
            inbox = MESSAGE_BUS.read_inbox(name)
            if inbox:
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        req_id = msg.get("request_id", "")
                        from mini_claude_code.team.protocols import (
                            handle_shutdown_response,
                        )

                        handle_shutdown_response(req_id, True, "Shutting down.")
                        return False
                    messages.append(
                        HumanMessage(content=f"<inbox>{json.dumps(msg)}</inbox>")
                    )
                return True

            # Scan task board for unclaimed tasks (s11)
            unclaimed = self._scan_unclaimed_tasks()
            if unclaimed:
                task = unclaimed[0]
                self._claim_task(task["id"], name)
                messages.append(
                    HumanMessage(
                        content=(
                            f"<auto-claimed>Task #{task['id']}: "
                            f"{task['subject']}</auto-claimed>"
                        )
                    )
                )
                # Identity re-injection if context is short
                if len(messages) <= 3:
                    member = self._find_member(name)
                    role = member["role"] if member else "agent"
                    messages.insert(0, make_identity_block(name, role))
                    messages.insert(1, AIMessage(content=f"I am {name}. Continuing."))
                return True

        return False  # timeout

    # ------------------------------------------------------------------
    # Task board scanning (s11)
    # ------------------------------------------------------------------
    @staticmethod
    def _scan_unclaimed_tasks() -> list[dict]:
        if not TASKS_DIR.exists():
            return []
        unclaimed = []
        for f in sorted(TASKS_DIR.glob("task_*.json")):
            task = json.loads(f.read_text())
            if (
                task.get("status") == "pending"
                and not task.get("owner")
                and not task.get("blockedBy")
            ):
                unclaimed.append(task)
        return unclaimed

    @staticmethod
    def _claim_task(task_id: int, owner: str) -> None:
        path = TASKS_DIR / f"task_{task_id}.json"
        if not path.exists():
            return
        task = json.loads(path.read_text())
        task["status"] = "in_progress"
        task["owner"] = owner
        task["updated_at"] = time.time()
        path.write_text(json.dumps(task, indent=2))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def list_members(self) -> str:
        if not self.config["members"]:
            return "(no teammates)"
        lines = []
        for m in self.config["members"]:
            lines.append(f"  {m['name']} (role: {m['role']}, status: {m['status']})")
        return "\n".join(lines)


# Singleton
TEAMMATE_MANAGER = TeammateManager()
