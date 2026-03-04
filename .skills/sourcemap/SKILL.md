---
name: sourcemap-analyze
description: Analyze a codebase with SourceMap AI — zip, index, and launch the interactive knowledge graph UI
---

# SourceMap AI Codebase Analysis

Use this skill when the user asks to **analyze the codebase**, **explore the codebase structure**,
**visualize dependencies**, **launch SourceMap**, or anything related to deep codebase analysis
with SourceMap AI.

SourceMap AI indexes a codebase into a knowledge graph (dependencies, call chains, clusters,
execution flows) and exposes it through an interactive web UI with AI chat.

## Paths

- **SourceMap CLI**: `/Users/himanshu/Downloads/SourceMap AI/sourcemap/dist/cli/index.js`
- **SourceMap Web UI**: `/Users/himanshu/Downloads/SourceMap AI/sourcemap-web/`

## Steps

### 1. Create a ZIP of the workspace

Zip the current workspace, **excluding** large/irrelevant directories:

```bash
cd $WORKDIR && zip -r /tmp/sourcemap-upload.zip . \
  -x ".venv/*" ".git/*" "node_modules/*" "__pycache__/*" \
     ".tasks/*" ".team/*" ".worktrees/*" ".transcripts/*" \
     "*.pyc" ".DS_Store" ".ruff_cache/*" "*.egg-info/*" \
     "dist/*" "build/*" ".sourcemap/*"
```

Tell the user the zip was created and its size.

### 2. Index the codebase with the SourceMap CLI

Run the SourceMap CLI `analyze` command on the current workspace:

```bash
node "/Users/himanshu/Downloads/SourceMap AI/sourcemap/dist/cli/index.js" analyze "$WORKDIR"
```

This creates a `.sourcemap/` directory in the workspace with the KuzuDB knowledge graph
index. Wait for indexing to complete — it may take a minute for larger codebases.

### 3. Start the SourceMap backend server

Start the local HTTP server so the web UI can connect to the indexed repo:

```bash
node "/Users/himanshu/Downloads/SourceMap AI/sourcemap/dist/cli/index.js" serve &
```

Run this in the **background**. The server typically starts on port 3001.

### 4. Start the SourceMap Web UI

Launch the Vite dev server for the interactive web UI:

```bash
cd "/Users/himanshu/Downloads/SourceMap AI/sourcemap-web" && npm run dev &
```

Run this in the **background**. It typically starts on `http://localhost:5173`.

### 5. Open the browser

```bash
open http://localhost:5173
```

On Linux use `xdg-open`, on macOS use `open`.

### 6. Report to the user

Tell the user:

- The codebase has been indexed into a knowledge graph
- The SourceMap web UI is running at `http://localhost:5173`
- The backend server is serving the indexed data
- A zip of the project is also available at `/tmp/sourcemap-upload.zip` if they want to
  use the hosted version at `https://sourcemap.vercel.app` (drag & drop the zip)
- They can explore: dependency graph visualization, AI chat about the codebase,
  call chain tracing, cluster analysis, impact analysis

### Alternative: Web-only approach (no CLI)

If the CLI indexing fails for any reason, fall back to the web-only approach:

1. Create the zip (step 1 above)
2. Open `https://sourcemap.vercel.app` in the browser
3. Tell the user to drag & drop `/tmp/sourcemap-upload.zip` into the web UI
4. Everything runs client-side in the browser (WASM) — no server needed

## Cleanup

When the user is done, kill the background processes:

```bash
# Find and kill sourcemap serve and vite dev server
pkill -f "sourcemap.*serve" 2>/dev/null
pkill -f "vite.*sourcemap-web" 2>/dev/null
```
