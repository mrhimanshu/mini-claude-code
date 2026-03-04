---
name: sourcemap-analyze
description: Analyze/explore/visualize a codebase — zip the project, launch SourceMap AI web UI, and auto-load it for interactive knowledge graph exploration. Use when user says "analyze", "explore codebase", "visualize", or "sourcemap".
---

# SourceMap AI Codebase Analysis

Follow these steps EXACTLY in order. Do NOT improvise or guess paths.
Run each step as a separate bash_tool call so the user can see progress.

## Step 1: Start the SourceMap Web UI (if not already running)

Check if the Vite dev server is running on port 5173. If not, start it in the background:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/ 2>/dev/null
```

If the response is NOT `200`, start the dev server:

```bash
cd "/Users/himanshu/Downloads/SourceMap AI/sourcemap-web" && npx vite --port 5173 &
```

Use `background_run` for this so it runs in the background. Then wait 8 seconds and
verify it is serving 200 on http://localhost:5173/.

If port 5173 already returns 200, skip starting it.

## Step 2: Create the ZIP and copy to web UI

Create a zip with all files inside a root folder named after the project.
The project name is auto-detected from the workspace directory name.
Run this as ONE bash command:

```bash
WORKDIR="/Users/himanshu/Downloads/mini-claude-code" && PROJ=$(basename "$WORKDIR") && rm -f "/tmp/${PROJ}.zip" && cd "$(dirname "$WORKDIR")" && zip -r "/tmp/${PROJ}.zip" "$PROJ" -x "${PROJ}/.venv/*" "${PROJ}/.git/*" "${PROJ}/node_modules/*" "${PROJ}/__pycache__/*" "${PROJ}/.tasks/*" "${PROJ}/.team/*" "${PROJ}/.worktrees/*" "${PROJ}/.transcripts/*" "${PROJ}/*.pyc" "${PROJ}/.DS_Store" "${PROJ}/.ruff_cache/*" "${PROJ}/*.egg-info/*" "${PROJ}/dist/*" "${PROJ}/build/*" "${PROJ}/.sourcemap/*" "${PROJ}/.env" "${PROJ}/uv.lock" && cp "/tmp/${PROJ}.zip" "/Users/himanshu/Downloads/SourceMap AI/sourcemap-web/public/${PROJ}.zip" && ls -lh "/tmp/${PROJ}.zip"
```

This produces a zip where all files are under `mini-claude-code/` (e.g. `mini-claude-code/pyproject.toml`).

## Step 3: Open the browser with auto-load

IMPORTANT: Run this EXACT command. Do NOT rename the parameter or change the URL structure.

```bash
PROJ=$(basename "/Users/himanshu/Downloads/mini-claude-code") && open "http://localhost:5173/?autozip=${PROJ}.zip"
```

This makes the web UI automatically fetch the zip and process it. The UI will
show a loading screen with progress (extracting, parsing, clustering, etc.).

## Step 4: Tell the user

Tell the user:
- The SourceMap AI web UI has opened in their browser
- The codebase is being auto-loaded and indexed (they will see a progress screen)
- Once indexing completes they can: explore the dependency graph, use AI chat to
  ask questions about the code, trace call chains, view clusters, and run
  impact analysis
