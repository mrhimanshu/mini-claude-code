"""Configuration and constants for Mini Claude Code."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_NAME: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "8192"))

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKDIR: Path = Path(os.getenv("WORKDIR", os.getcwd())).resolve()

# ---------------------------------------------------------------------------
# Runtime state directories (created lazily)
# ---------------------------------------------------------------------------
TASKS_DIR: Path = WORKDIR / ".tasks"
TEAM_DIR: Path = WORKDIR / ".team"
INBOX_DIR: Path = TEAM_DIR / "inbox"
WORKTREES_DIR: Path = WORKDIR / ".worktrees"
TRANSCRIPTS_DIR: Path = WORKDIR / ".transcripts"
SKILLS_DIR: Path = WORKDIR / ".skills"

# ---------------------------------------------------------------------------
# Context compaction thresholds (s06)
# ---------------------------------------------------------------------------
TOKEN_THRESHOLD: int = int(os.getenv("TOKEN_THRESHOLD", "50000"))
KEEP_RECENT_TOOL_RESULTS: int = 3  # micro-compact keeps last N

# ---------------------------------------------------------------------------
# Agent limits
# ---------------------------------------------------------------------------
MAX_AGENT_ITERATIONS: int = int(os.getenv("MAX_AGENT_ITERATIONS", "100"))
MAX_SUBAGENT_ITERATIONS: int = 30
NAG_ROUNDS_THRESHOLD: int = 3  # remind to update todos after N rounds

# ---------------------------------------------------------------------------
# Background tasks (s08)
# ---------------------------------------------------------------------------
BG_COMMAND_TIMEOUT: int = 300  # seconds

# ---------------------------------------------------------------------------
# Autonomous agents (s11)
# ---------------------------------------------------------------------------
IDLE_POLL_INTERVAL: int = 5  # seconds
IDLE_TIMEOUT: int = 60  # seconds before auto-shutdown

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE: str = """\
You are a powerful coding agent operating at {workdir}.

You have access to tools for:
- Running bash commands
- Reading, writing, and editing files
- Managing a todo list for tracking multi-step tasks
- Loading skills for domain-specific workflows
- Creating and managing tasks with dependencies
- Running background commands
- Spawning subagents for isolated exploration
- Managing teammate agents for parallel work
- Creating git worktrees for task isolation

{skills_section}

Guidelines:
- Use the todo tool to plan multi-step tasks. Mark items in_progress before starting, completed when done.
- Prefer tools over prose. Act, don't describe.
- Use subagents (task tool) to explore without polluting your context.
- Use the task board for durable multi-step work that survives compression.
- For long-running commands, use background execution.
- Keep responses concise and actionable.
"""
