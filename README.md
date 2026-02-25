# Mini Claude Code

A LangGraph-based coding agent inspired by [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code). Implements all 12 sessions (s01-s12) — from the core agent loop through autonomous agent teams with git worktree isolation — as a single, working interactive CLI.

**Model:** Claude Sonnet 4 (via Anthropic API)
**Framework:** LangGraph + LangChain
**Package manager:** uv

---

## Quick Start

```bash
# 1. Clone / enter the project
cd mini-claude-code

# 2. Create a .env file with your API key
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

# 3. Run the interactive REPL
uv run python -m mini_claude_code.main
```

You'll see a Rich-formatted terminal. Type prompts, watch tool calls execute, and use slash commands for introspection.

---

## Slash Commands

| Command    | Description                        |
|------------|------------------------------------|
| `/help`    | Show all available commands         |
| `/todos`   | Display current todo list           |
| `/tasks`   | Show the file-based task board      |
| `/team`    | Show teammate roster and statuses   |
| `/inbox`   | Check the lead agent's inbox        |
| `/bg`      | Show background task statuses       |
| `/compact` | Trigger manual context compaction   |
| `/model`   | Show current model name             |
| `/quit`    | Exit the REPL                       |

---

## Architecture

The agent loop is a LangGraph `StateGraph` that cycles until the LLM stops calling tools:

```
START
  |
  v
preprocess -----> call_llm -----> router
  ^                                 |
  |                            tool_calls?
  |                           /         \
  |                         yes          no
  |                          |            |
  +------- tools <-----------+           END
```

**preprocess** — micro-compacts old tool results, drains background task notifications, checks teammate inboxes, injects todo nag reminders, triggers auto-compaction if tokens exceed the threshold.

**call_llm** — calls `ChatAnthropic` with 28 bound tools and a system prompt containing skill descriptions.

**tools** — executes tool calls and returns results.

**router** — if the LLM made tool calls, loop back to `preprocess`; otherwise exit.

---

## Features (mapped to learn-claude-code sessions)

### s01 — Agent Loop
`agent/graph.py`, `agent/nodes.py`

The LangGraph `StateGraph` implements the core `while tool_use: loop`. The `route_response` conditional edge checks for `tool_calls` on the last `AIMessage` and either routes to the `tools` node or to `END`.

### s02 — Tool Use
`tools/bash_tool.py`, `tools/filesystem.py`

28 tools registered via LangChain `@tool` decorators. A dispatch map is implicit in LangGraph's `ToolNode`-style execution. `safe_path()` enforces workspace sandboxing — all file operations are resolved relative to `WORKDIR` and rejected if they escape it.

### s03 — TodoWrite
`tools/todo.py`, `agent/nodes.py`

`TodoManager` tracks items with `pending | in_progress | completed | cancelled` statuses. Only one item can be `in_progress` at a time. A nag reminder is injected into the conversation when the agent goes 3+ rounds without calling `todo_write`.

### s04 — Subagent
`agent/subagent.py`, `tools/subagent.py`

The `delegate_task` tool spawns a fresh `ChatAnthropic` instance with a clean message list and child-only tools (no recursive spawning). Only the subagent's final text response returns to the parent, keeping the parent's context clean.

### s05 — Skill Loading
`tools/skills.py`, `.skills/*.md`

Two-layer injection. **Layer 1:** short skill descriptions are injected into the system prompt (~100 tokens each). **Layer 2:** the `load_skill` tool loads the full skill body on demand, wrapped in `<skill>` tags. Skills are Markdown files with YAML frontmatter in `.skills/`.

### s06 — Context Compaction
`context/compactor.py`, `tools/compact.py`

Three-layer compression pipeline:
- **Micro-compact** (every turn) — replaces tool results older than the last 3 with `[Previous tool result truncated]`.
- **Auto-compact** (at threshold) — when estimated tokens exceed 50,000, the full conversation is summarized by the LLM and replaced. The original transcript is saved to `.transcripts/`.
- **Manual compact** — the `compact` tool or `/compact` slash command triggers summarization on demand.

### s07 — Task System
`tools/task_board.py`

File-based `TaskManager` persists tasks as `.tasks/task_*.json`. Each task has `blockedBy` and `blocks` arrays forming a dependency graph. Completing a task auto-clears it from downstream tasks' `blockedBy` lists. Survives context compaction because state lives on disk.

### s08 — Background Tasks
`tools/background.py`

`BackgroundManager` runs commands in daemon threads. Results accumulate in a thread-safe notification queue that is drained by the `preprocess` node before each LLM call, injected as `<background-results>` messages.

### s09 — Agent Teams
`team/manager.py`, `team/bus.py`, `tools/team.py`

`TeammateManager` spawns named teammates, each running its own `ChatAnthropic` agent loop in a daemon thread. `MessageBus` provides append-only JSONL inboxes in `.team/inbox/` with drain-on-read semantics. Five message types: `message`, `broadcast`, `shutdown_request`, `shutdown_response`, `plan_approval_response`.

### s10 — Team Protocols
`team/protocols.py`

Shutdown and plan approval share the same `request_id` handshake FSM: `pending -> approved | rejected`. The lead initiates with a unique `request_id`; the teammate responds referencing it. Both protocols use in-memory tracker dicts correlated by request ID.

### s11 — Autonomous Agents
`team/manager.py` (idle polling), `team/autonomous.py`

When a teammate finishes its work, it enters an idle polling phase: every 5 seconds it checks its inbox and scans the task board for unclaimed tasks. If it finds work, it auto-claims the task and resumes. After 60 seconds with no work, it shuts down. Identity re-injection after context compression ensures teammates remember their role.

### s12 — Worktree Isolation
`tools/worktree.py`, `events.py`

`WorktreeManager` creates git worktrees bound to tasks by ID. Each worktree gets its own directory and branch. The `worktree_remove` closeout pattern handles teardown + task completion atomically. An append-only `EventStream` in `.worktrees/events.jsonl` emits before/after/failed events for every lifecycle transition.

---

## Project Structure

```
mini-claude-code/
├── .env                          # ANTHROPIC_API_KEY (not committed)
├── .skills/                      # Skill definition files (Markdown + YAML frontmatter)
│   ├── code_review.md
│   └── git_workflow.md
├── pyproject.toml                # uv project config + dependencies
├── src/mini_claude_code/
│   ├── __init__.py
│   ├── main.py                   # Interactive REPL (Rich + prompt-toolkit)
│   ├── config.py                 # All configuration, paths, thresholds
│   ├── events.py                 # Append-only JSONL event stream (s12)
│   ├── agent/
│   │   ├── graph.py              # LangGraph StateGraph construction
│   │   ├── nodes.py              # preprocess, call_llm, tools, router nodes
│   │   ├── state.py              # AgentState TypedDict
│   │   └── subagent.py           # Fresh-context subagent runner (s04)
│   ├── context/
│   │   └── compactor.py          # 3-layer compression + identity re-injection
│   ├── team/
│   │   ├── autonomous.py         # Task board scanning + claiming (s11)
│   │   ├── bus.py                # JSONL MessageBus (s09)
│   │   ├── manager.py            # TeammateManager lifecycle (s09/s11)
│   │   └── protocols.py          # Shutdown + plan approval FSMs (s10)
│   └── tools/
│       ├── __init__.py           # Tool registry (28 parent, 8 child)
│       ├── background.py         # BackgroundManager + daemon threads (s08)
│       ├── bash_tool.py          # Shell execution with timeout (s01)
│       ├── compact.py            # Manual compact trigger (s06)
│       ├── filesystem.py         # read/write/edit with path sandbox (s02)
│       ├── skills.py             # SkillLoader two-layer system (s05)
│       ├── subagent.py           # delegate_task tool (s04)
│       ├── task_board.py         # TaskManager with dependency graph (s07)
│       ├── team.py               # Team tools: spawn, send, inbox (s09-s11)
│       ├── todo.py               # TodoManager + nag injection (s03)
│       └── worktree.py           # WorktreeManager + git worktrees (s12)
└── Runtime state (git-ignored, created on demand):
    ├── .tasks/                   # task_*.json files
    ├── .team/                    # config.json + inbox/*.jsonl
    ├── .worktrees/               # index.json + events.jsonl + worktree dirs
    └── .transcripts/             # Saved conversation transcripts
```

---

## Configuration

All settings are in `.env` or environment variables:

| Variable               | Default                      | Description                          |
|------------------------|------------------------------|--------------------------------------|
| `ANTHROPIC_API_KEY`    | *(required)*                 | Anthropic API key                    |
| `ANTHROPIC_MODEL`      | `claude-sonnet-4-20250514`   | Model ID                             |
| `MAX_TOKENS`           | `8192`                       | Max tokens per LLM response          |
| `TOKEN_THRESHOLD`      | `50000`                      | Token count that triggers auto-compact |
| `MAX_AGENT_ITERATIONS` | `100`                        | Safety limit for agent loop cycles   |
| `WORKDIR`              | Current working directory    | Workspace root for file sandboxing   |

---

## Tools (28 total)

| Tool                | Source  | Description                                      |
|---------------------|---------|--------------------------------------------------|
| `bash_tool`         | s01     | Run shell commands with timeout                  |
| `read_file`         | s02     | Read files with line numbers and offset/limit    |
| `write_file`        | s02     | Write files with parent directory creation       |
| `edit_file`         | s02     | Exact string replacement in files                |
| `todo_write`        | s03     | Update the in-memory todo list                   |
| `delegate_task`     | s04     | Spawn a fresh-context subagent                   |
| `load_skill`        | s05     | Load a skill's full instructions on demand       |
| `compact`           | s06     | Trigger manual context compaction                |
| `task_create`       | s07     | Create a task on the board                       |
| `task_update`       | s07     | Update task status, owner, dependencies          |
| `task_list`         | s07     | List all tasks                                   |
| `task_get`          | s07     | Get full task details                            |
| `background_run`    | s08     | Run a command in a background thread             |
| `background_check`  | s08     | Check background task status                     |
| `spawn_teammate`    | s09     | Spawn a persistent teammate agent                |
| `send_message`      | s09     | Send a message to a teammate's inbox             |
| `read_inbox`        | s09     | Read and drain the lead's inbox                  |
| `broadcast_message` | s09     | Broadcast to all teammates                       |
| `list_teammates`    | s09     | Show team roster                                 |
| `request_shutdown`  | s10     | Request teammate graceful shutdown               |
| `plan_approval`     | s10     | Approve or reject a teammate's plan              |
| `worktree_create`   | s12     | Create an isolated git worktree                  |
| `worktree_list`     | s12     | List all worktrees                               |
| `worktree_status`   | s12     | Git status inside a worktree                     |
| `worktree_run`      | s12     | Run a command inside a worktree                  |
| `worktree_keep`     | s12     | Mark worktree as preserved                       |
| `worktree_remove`   | s12     | Remove worktree (optionally complete bound task) |
| `worktree_events`   | s12     | Query the lifecycle event stream                 |

---

## Example Prompts

```
# Basic tool use
Create a Python file that prints hello world, then run it

# Todo tracking
Refactor config.py: extract constants, add docstrings, add type hints

# Subagent delegation
Use a subtask to analyze all Python files and summarize the architecture

# Task board with dependencies
Create 3 tasks: "design API", "implement API", "write tests" — each blocking the next

# Background execution
Run "sleep 5 && echo done" in the background, then create a config file while it runs

# Team collaboration
Spawn alice (coder) and bob (tester). Have alice write a module, then message bob to test it.

# Worktree isolation
Create a worktree "auth-refactor" bound to task 1, run tests inside it
```

---

## License

MIT
