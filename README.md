# Mini Claude Code

A fully async, thread-safe LangGraph-based coding agent inspired by [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code). Implements all 12 sessions (s01-s12) — from the core agent loop through autonomous agent teams with git worktree isolation — as a single, working interactive CLI.

**Model:** Claude Sonnet 4 (via Anthropic API)
**Framework:** LangGraph + LangChain (fully async)
**Package manager:** uv

### Concurrency Model

- **Async everywhere** — every tool, node, and LLM call uses `async/await`
- **Parallel tool execution** — multiple tool calls from a single LLM response run concurrently via `asyncio.gather`
- **Non-blocking subprocess** — `asyncio.create_subprocess_shell` instead of blocking `subprocess.run`
- **Non-blocking LLM calls** — `ainvoke` / `astream` for all Anthropic API calls
- **Async REPL** — `prompt_toolkit.prompt_async` keeps the event loop responsive
- **asyncio.Lock on all shared state** — TodoManager, TaskManager, MessageBus, EventStream, TeammateManager config, protocol trackers
- **Atomic task claiming** — `TaskManager.claim_task()` is lock-protected; concurrent claims are serialized and only one wins
- **Atomic inbox drain** — `MessageBus.read_inbox()` reads+drains under a single lock, preventing the TOCTOU message-loss bug
- **Teammates as asyncio.Task** — not threads; teammates share the event loop for true cooperative concurrency
- **Per-file edit locks** — `edit_file` uses per-path `asyncio.Lock` to prevent concurrent edit races

### Streaming & Live Display

- **Real-time token streaming** — LLM responses appear token-by-token as they are generated, using `streaming=True` on `ChatAnthropic` with an `AsyncCallbackHandler` that writes directly to stdout
- **Animated thinking spinner** — a braille-dot spinner (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) runs as a background `asyncio.Task` during LLM inference and tool execution, providing visual feedback that the agent is working
- **Phase-aware indicators** — the spinner shows `Thinking...` (blue) while the LLM generates, and `Running tools...` (cyan) during tool execution
- **Seamless transitions** — the spinner is automatically replaced by streaming text on the first token, with no flicker or duplicate output
- **Callback propagation** — `RunnableConfig` with callbacks is passed through LangGraph nodes to the LLM, so token events fire correctly even inside the graph execution

---

## Quick Start

```bash
# 1. Clone / enter the project
cd mini-claude-code

# 2. Create a .env file with your API key
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

# 3. Run the interactive REPL
uv run mini-claude
```

You'll see a Rich-formatted terminal with an animated thinking spinner. LLM responses stream in token-by-token as they are generated. Type prompts, watch tool calls execute, and use slash commands for introspection.

---

## Plan Mode — Collaborative Plan Review

Mini Claude Code supports a **Plan Mode** for collaborative, multi-user plan review before execution. Press **Tab** or type `/mode` to switch between Build Mode (default) and Plan Mode.

### How It Works

1. **Generate a plan** — In Plan Mode, type your request. The LLM produces a structured markdown plan (rendered with Rich formatting in the terminal).
2. **Share for review** — A local web server starts automatically and provides a URL. If ngrok or cloudflared is available, a public tunnel URL is created for remote reviewers.
3. **Collaborate in real-time** — Reviewers open the URL in their browser, join with a username, and can:
   - **Edit** the plan directly (contenteditable with Turndown.js for lossless markdown round-tripping)
   - **Delete** or **Add Text** via the selection toolbar (tracked as `<ins>`/`<del>` with per-user colors)
   - **Annotate** specific text ranges (Google Docs-style sidebar comments)
   - **Request Changes** — adds feedback as an annotation without killing the flow; the plan stays editable
4. **Per-user color coding** — Each user is assigned a unique color from an 8-color palette. Their edits, annotations, user chips, and edit history entries are all rendered in that color, so you can instantly see who changed what.
5. **Multi-user approval** — Every connected reviewer (including the CLI user) must approve. The approval bar shows per-user status with checkmarks (`2/4 approved`). The terminal displays each approval as it happens:
   ```
   alice approved the plan (1/3)
   bob approved the plan (2/3)
   ```
   If a reviewer disconnects before approving, they are removed from the required set — remaining approvers are sufficient.
6. **Execute** — Once all reviewers approve, the final edited plan text is sent to the LLM for execution. The plan sent to the LLM is **clean** — no annotations, no reviewer markers, no tracking metadata. Just the approved text.
7. **Reject** — Any reviewer can fully reject/abandon the plan, which ends the flow.

### Plan Mode Slash Commands

| Command                  | Description                                          |
|--------------------------|------------------------------------------------------|
| `/mode`                  | Toggle between Build and Plan mode (or press Tab)    |
| `/approve`               | Approve the plan (counts as one reviewer)            |
| `/reject [reason]`       | Reject and abandon the plan                          |
| `/request-changes [msg]` | Request changes (plan stays open for editing)        |
| `/share`                 | Show the plan sharing URL                            |
| `/plan`                  | Display the current plan in the terminal             |

---

## Slash Commands

| Command                  | Description                                          |
|--------------------------|------------------------------------------------------|
| `/help`                  | Show all available commands                          |
| `/mode`                  | Toggle Build/Plan mode (or press Tab)                |
| `/approve`               | Approve the current plan locally                     |
| `/reject [reason]`       | Reject and abandon the plan                          |
| `/request-changes [msg]` | Request changes (plan stays open for editing)        |
| `/share`                 | Show the plan sharing URL                            |
| `/plan`                  | Display the current plan                             |
| `/todos`                 | Display current todo list                            |
| `/tasks`                 | Show the file-based task board                       |
| `/team`                  | Show teammate roster and statuses                    |
| `/inbox`                 | Check the lead agent's inbox                         |
| `/bg`                    | Show background task statuses                        |
| `/compact`               | Trigger manual context compaction                    |
| `/model`                 | Show current model name                              |
| `/clear`                 | Reset .tasks and .team state                         |
| `/quit`                  | Exit the REPL                                        |

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

**call_llm** — calls `ChatAnthropic` (with `streaming=True`) with 28 bound tools and a system prompt containing skill descriptions. Tokens stream to the terminal in real-time via an `AsyncCallbackHandler`.

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
`tools/skills.py`, `.skills/*/SKILL.md`

Two-layer injection. **Layer 1:** short skill descriptions are injected into the system prompt (~100 tokens each). **Layer 2:** the `load_skill` tool loads the full skill body on demand, wrapped in `<skill>` tags. Each skill is a folder under `.skills/` containing a `SKILL.md` file with YAML frontmatter (`name` and `description`) and markdown instructions.

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

### Plan Mode — Collaborative Plan Review & Execution
`plan/manager.py`, `plan/server.py`, `plan/templates.py`, `plan/tunnel.py`, `main.py`

A full collaborative plan review system built on top of the agent:

- **Plan generation** — A plan-specific LangGraph (single LLM call, no tools) generates structured markdown plans. The plan system prompt instructs the LLM to produce headings, code fences, and bullet points.
- **Real-time collaboration** — An embedded aiohttp web server with WebSocket support serves an interactive SPA. Multiple users can edit the plan simultaneously with conflict-free updates.
- **Per-user color tracking** — Each collaborator is assigned a unique color from an 8-color palette. Edits (`<ins>`/`<del>` from the selection toolbar), annotations, user chips, and edit history are all rendered in the user's color.
- **Lossless markdown editing** — Turndown.js converts the edited HTML back to markdown on every change, preserving headings, bold, code blocks, lists, and links through the edit round-trip (solving the `contenteditable` → `innerText` data loss problem).
- **Multi-user approval** — `PlanManager` tracks `_approved_users` and `_connected_users` sets. `record_approval()` adds a user and checks if all connected users (including the CLI user) have approved. Users who disconnect are removed from the required set. The approval bar shows per-user status with checkmarks.
- **Terminal rendering** — Plan output uses Rich `Markdown` rendering (no raw markdown symbols). Approval progress is displayed in real-time as each reviewer approves.
- **Clean execution** — The final plan sent to the LLM contains only the approved text — no annotations, no reviewer markers, no tracking metadata.

---

## Project Structure

```
mini-claude-code/
├── .env                          # ANTHROPIC_API_KEY (not committed)
├── .skills/                      # Skill folders (each with SKILL.md)
│   ├── code-review/SKILL.md
│   └── git-workflow/SKILL.md
├── pyproject.toml                # uv project config + dependencies
├── src/mini_claude_code/
│   ├── __init__.py
│   ├── main.py                   # Interactive REPL with streaming + animated spinner
│   ├── config.py                 # All configuration, paths, thresholds
│   ├── events.py                 # Append-only JSONL event stream (s12)
│   ├── agent/
│   │   ├── graph.py              # LangGraph StateGraph construction
│   │   ├── nodes.py              # preprocess, call_llm, tools, router nodes
│   │   ├── state.py              # AgentState TypedDict
│   │   └── subagent.py           # Fresh-context subagent runner (s04)
│   ├── context/
│   │   └── compactor.py          # 3-layer compression + identity re-injection
│   ├── plan/
│   │   ├── __init__.py           # Re-exports PLAN_MANAGER, Plan, Annotation, Edit
│   │   ├── manager.py            # Plan data model, PlanManager singleton, multi-user approval
│   │   ├── server.py             # Embedded aiohttp web server + WebSocket collaboration
│   │   ├── templates.py          # Full HTML/CSS/JS SPA for plan review (per-user colors, Turndown.js)
│   │   └── tunnel.py             # Auto-detect ngrok/cloudflared for public URL tunneling
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
| `PLAN_APPROVAL_TIMEOUT`| `3600`                       | Seconds to wait for plan approval    |
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

# Plan Mode (press Tab first to switch to Plan Mode)
Design a REST API for a user management system with auth, CRUD, and rate limiting
# -> Generates a plan, starts sharing server, share the URL with your team
# -> Reviewers edit, annotate, request changes, then approve when ready
# -> Once all approve, the agent executes the final plan
```

---

## License

MIT
