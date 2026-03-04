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
# Human-in-the-loop approval for file changes
# ---------------------------------------------------------------------------
REQUIRE_APPROVAL: bool = os.getenv("REQUIRE_APPROVAL", "true").lower() in (
    "true",
    "1",
    "yes",
)

# ---------------------------------------------------------------------------
# Plan mode (mode switching + plan sharing)
# ---------------------------------------------------------------------------
PLAN_APPROVAL_TIMEOUT: int = int(os.getenv("PLAN_APPROVAL_TIMEOUT", "3600"))  # 1hr

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
- **Skills first**: Before starting a task, check if an available skill matches the
  user's request. If it does, call load_skill(name="<skill-name>") FIRST to get the
  full instructions, then follow them step by step. Always prefer skill instructions
  over improvising.
- Use the todo tool to plan multi-step tasks. Mark items in_progress before starting, completed when done.
- Prefer tools over prose. Act, don't describe.
- Use subagents (task tool) to explore without polluting your context.
- Use the task board for durable multi-step work that survives compression.
- For long-running commands, use background execution.
- Keep responses concise and actionable.
"""

# ---------------------------------------------------------------------------
# Plan mode system prompt
# ---------------------------------------------------------------------------
PLAN_SYSTEM_PROMPT_TEMPLATE: str = """\
You are a powerful coding agent operating at {workdir}.

You are in PLAN MODE. Produce a clear, detailed implementation plan in natural
markdown. Do NOT execute anything — only plan.

Write the plan as a readable document:
- Use ## headings to separate major phases or sections
- Use numbered lists for sequential steps
- Use bullet points for details, considerations, or alternatives
- Include ```code fences``` with concrete code snippets where helpful
- Explain *why* each step is needed, not just *what* to do
- Mention files to create or modify by path
- Call out risks, edge cases, or decisions that need review

This plan will be shared with collaborators who can edit the text, delete
sections, add their own notes, and annotate specific parts before approving
it for execution. Write naturally — as if drafting a technical design doc.

{skills_section}
"""
