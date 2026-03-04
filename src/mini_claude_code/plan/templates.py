"""HTML/CSS/JS template for the interactive plan document editor SPA.

Features:
- Markdown rendering via marked.js + code highlighting via Prism.js (CDN)
- Full document editing (contenteditable)
- Text selection floating toolbar: Annotate, Delete, Add Text
- Change tracking: <ins> (underlined green) and <del> (strikethrough red)
- Annotation sidebar (Google Docs style, anchored to char ranges)
- Real-time WebSocket collaboration with online user badges
- Edit history panel
- Approve / Reject buttons
- Dark theme with cosmetic polish
"""

from __future__ import annotations

PLAN_EDITOR_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Plan Review - Mini Claude Code</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" rel="stylesheet">
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --surface2: #21262d; --surface3: #1c2333;
    --border: #30363d; --text: #e6edf3; --text-dim: #8b949e; --text-faint: #484f58;
    --accent: #58a6ff; --green: #3fb950; --red: #f85149;
    --yellow: #d29922; --purple: #bc8cff; --orange: #f0883e;
    --ins-bg: rgba(63,185,80,0.12); --ins-border: rgba(63,185,80,0.4);
    --del-bg: rgba(248,81,73,0.12); --del-border: rgba(248,81,73,0.4);
    --ann-bg: rgba(188,140,255,0.15); --ann-border: rgba(188,140,255,0.5);
    --radius: 8px;
    --mono: 'SF Mono','Cascadia Code','Fira Code','JetBrains Mono',monospace;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
    background: var(--bg); color: var(--text); line-height:1.7; min-height:100vh;
  }

  /* ---- Top gradient bar ---- */
  .top-bar {
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--purple), var(--green));
  }

  /* ---- Layout ---- */
  .layout { display:flex; max-width:1200px; margin:0 auto; min-height:100vh; }
  .main-col { flex:1; min-width:0; padding:24px 32px; }
  .sidebar-col {
    width:300px; flex-shrink:0; border-left:1px solid var(--border);
    padding:16px; overflow-y:auto; max-height:100vh; position:sticky; top:0;
  }

  /* ---- Header ---- */
  .header {
    display:flex; justify-content:space-between; align-items:center;
    padding:16px 0; margin-bottom:8px; border-bottom:1px solid var(--border);
  }
  .header-left { display:flex; align-items:center; gap:12px; }
  .header-left .logo {
    font-size:13px; font-weight:700; color:var(--accent);
    padding:4px 10px; border:1px solid var(--accent); border-radius:4px;
    letter-spacing:0.5px;
  }
  .header h1 { font-size:16px; font-weight:600; }
  .status {
    padding:3px 10px; border-radius:20px; font-size:11px; font-weight:700;
    text-transform:uppercase; letter-spacing:0.5px;
  }
  .status-draft { background:var(--surface2); color:var(--text-dim); }
  .status-shared { background:#1f3a5f; color:var(--accent); }
  .status-approved { background:#1a3a2a; color:var(--green); }
  .status-rejected { background:#3d1f1f; color:var(--red); }
  .status-changes_requested { background:#3d2e0f; color:var(--yellow); }

  /* ---- Online users ---- */
  .online-bar {
    display:flex; align-items:center; gap:8px; padding:8px 0;
    margin-bottom:16px; font-size:12px; color:var(--text-dim);
  }
  .pulse-dot {
    width:7px; height:7px; border-radius:50%; background:var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .user-chip {
    padding:2px 8px; background:var(--surface2); border-radius:10px;
    font-size:11px; color:var(--accent); font-weight:500;
  }

  /* ---- Document area ---- */
  .document {
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); padding:28px 32px; min-height:300px;
    font-size:15px; line-height:1.8; outline:none; position:relative;
  }
  .document:focus { border-color:var(--accent); }

  /* Markdown-rendered content styles */
  .document h1,.document h2,.document h3 { color:var(--text); margin:20px 0 8px; font-weight:600; }
  .document h1 { font-size:22px; border-bottom:1px solid var(--border); padding-bottom:6px; }
  .document h2 { font-size:18px; }
  .document h3 { font-size:15px; }
  .document p { margin:8px 0; }
  .document ul,.document ol { padding-left:24px; margin:8px 0; }
  .document li { margin:4px 0; }
  .document blockquote {
    border-left:3px solid var(--accent); padding:4px 16px; margin:12px 0;
    color:var(--text-dim); background:var(--surface2); border-radius:0 4px 4px 0;
  }
  .document pre {
    background:var(--bg); border:1px solid var(--border); border-radius:6px;
    padding:14px 18px; overflow-x:auto; margin:12px 0; font-size:13px;
    font-family:var(--mono); line-height:1.5;
  }
  .document code {
    font-family:var(--mono); font-size:0.9em;
    background:var(--surface2); padding:1px 5px; border-radius:3px;
  }
  .document pre code { background:none; padding:0; font-size:13px; }
  .document a { color:var(--accent); text-decoration:none; }
  .document hr { border:none; border-top:1px solid var(--border); margin:16px 0; }
  .document strong { color:var(--text); font-weight:600; }
  .document em { font-style:italic; color:var(--text-dim); }

  /* ---- Change tracking ---- */
  ins.tracked {
    text-decoration:none; border-bottom:2px solid var(--ins-border);
    background:var(--ins-bg); padding:0 1px; border-radius:2px;
    cursor:help; position:relative;
  }
  del.tracked {
    text-decoration:line-through; color:var(--red);
    background:var(--del-bg); padding:0 1px; border-radius:2px;
    cursor:help; opacity:0.8; position:relative;
  }
  ins.tracked:hover::after, del.tracked:hover::after {
    content:attr(data-info); position:absolute; bottom:100%; left:0;
    background:var(--surface2); color:var(--text-dim); font-size:11px;
    padding:3px 8px; border-radius:4px; white-space:nowrap; z-index:100;
    border:1px solid var(--border); pointer-events:none;
  }

  /* ---- Annotation highlights ---- */
  mark.annotation {
    background:var(--ann-bg); border-bottom:2px solid var(--ann-border);
    cursor:pointer; border-radius:2px; padding:0 1px;
    transition:background 0.15s;
  }
  mark.annotation:hover { background:rgba(188,140,255,0.3); }
  mark.annotation.active { background:rgba(188,140,255,0.35); box-shadow:0 0 0 1px var(--purple); }

  /* ---- Floating selection toolbar ---- */
  .sel-toolbar {
    position:absolute; display:none; z-index:500;
    background:var(--surface); border:1px solid var(--border);
    border-radius:6px; padding:4px; box-shadow:0 4px 16px rgba(0,0,0,0.5);
    gap:2px; flex-direction:row;
  }
  .sel-toolbar.visible { display:flex; }
  .sel-toolbar button {
    background:none; border:none; color:var(--text-dim); padding:6px 12px;
    border-radius:4px; cursor:pointer; font-size:12px; font-weight:500;
    white-space:nowrap; transition:all 0.1s;
  }
  .sel-toolbar button:hover { background:var(--surface2); color:var(--text); }
  .sel-toolbar .tb-annotate:hover { color:var(--purple); }
  .sel-toolbar .tb-delete:hover { color:var(--red); }
  .sel-toolbar .tb-addtext:hover { color:var(--green); }
  .sel-toolbar-sep { width:1px; background:var(--border); margin:4px 2px; }

  /* ---- Annotation input popover ---- */
  .ann-popover {
    position:absolute; display:none; z-index:600;
    background:var(--surface); border:1px solid var(--purple);
    border-radius:8px; padding:12px; width:280px;
    box-shadow:0 8px 24px rgba(0,0,0,0.5);
  }
  .ann-popover.visible { display:block; }
  .ann-popover textarea {
    width:100%; background:var(--bg); border:1px solid var(--border); color:var(--text);
    padding:8px; border-radius:4px; font-size:13px; resize:vertical;
    min-height:60px; outline:none; font-family:inherit;
  }
  .ann-popover textarea:focus { border-color:var(--purple); }
  .ann-popover .ann-actions { display:flex; justify-content:flex-end; gap:6px; margin-top:8px; }
  .ann-popover button {
    padding:5px 14px; border-radius:4px; cursor:pointer; font-size:12px; font-weight:600;
    border:none;
  }
  .ann-popover .btn-cancel { background:var(--surface2); color:var(--text-dim); }
  .ann-popover .btn-save { background:var(--purple); color:white; }

  /* ---- Sidebar: annotations list ---- */
  .sidebar-title {
    font-size:12px; font-weight:700; text-transform:uppercase;
    letter-spacing:0.8px; color:var(--text-dim); margin-bottom:12px;
  }
  .ann-card {
    background:var(--surface); border:1px solid var(--border);
    border-radius:6px; padding:10px 12px; margin-bottom:8px;
    cursor:pointer; transition:border-color 0.15s; font-size:13px;
  }
  .ann-card:hover { border-color:var(--purple); }
  .ann-card.active { border-color:var(--purple); background:var(--surface2); }
  .ann-card-user { color:var(--accent); font-weight:600; font-size:12px; }
  .ann-card-quote {
    color:var(--text-dim); font-style:italic; font-size:12px;
    margin:4px 0; padding:4px 8px; border-left:2px solid var(--purple);
    background:var(--bg); border-radius:0 4px 4px 0;
    max-height:40px; overflow:hidden;
  }
  .ann-card-text { color:var(--text); margin-top:6px; }
  .ann-card-time { color:var(--text-faint); font-size:11px; margin-top:4px; }
  .ann-card-resolve {
    font-size:11px; color:var(--green); cursor:pointer; margin-top:4px;
    opacity:0.7; transition:opacity 0.1s;
  }
  .ann-card-resolve:hover { opacity:1; }
  .ann-card.resolved { opacity:0.5; }
  .ann-card.resolved .ann-card-resolve { display:none; }

  /* ---- Edit history panel ---- */
  .history-toggle {
    font-size:12px; color:var(--text-dim); cursor:pointer;
    margin-top:20px; padding:6px 0; border-top:1px solid var(--border);
  }
  .history-toggle:hover { color:var(--text); }
  .history-list { display:none; margin-top:8px; }
  .history-list.visible { display:block; }
  .edit-entry {
    font-size:11px; color:var(--text-dim); padding:4px 0;
    border-bottom:1px solid var(--border);
  }
  .edit-entry .edit-user { color:var(--accent); font-weight:600; }
  .edit-entry .edit-type-insert { color:var(--green); }
  .edit-entry .edit-type-delete { color:var(--red); }
  .edit-entry .edit-type-replace { color:var(--yellow); }

  /* ---- Approval bar ---- */
  .approval-bar {
    position:sticky; bottom:0; background:var(--surface);
    border:1px solid var(--border); border-radius:var(--radius);
    padding:14px 20px; margin-top:24px;
    display:flex; justify-content:space-between; align-items:center;
    box-shadow:0 -4px 20px rgba(0,0,0,0.3);
  }
  .approval-bar .info { font-size:13px; color:var(--text-dim); }
  .approval-buttons { display:flex; gap:8px; }
  .btn-approve {
    background:var(--green); color:var(--bg); border:none;
    padding:8px 24px; border-radius:6px; cursor:pointer;
    font-size:14px; font-weight:600; transition:opacity 0.15s;
  }
  .btn-approve:hover { opacity:0.9; }
  .btn-reject {
    background:none; color:var(--red); border:1px solid var(--red);
    padding:8px 24px; border-radius:6px; cursor:pointer;
    font-size:14px; font-weight:600; transition:all 0.15s;
  }
  .btn-reject:hover { background:var(--red); color:white; }
  .btn-request-changes {
    background:none; color:var(--yellow); border:1px solid var(--yellow);
    padding:8px 24px; border-radius:6px; cursor:pointer;
    font-size:14px; font-weight:600; transition:all 0.15s;
  }
  .btn-request-changes:hover { background:var(--yellow); color:var(--bg); }
  .btn-request-changes:disabled { opacity:0.4; cursor:not-allowed; }
  .approval-status {
    display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:12px;
  }
  .approval-count { color:var(--text-dim); font-weight:500; }
  .approval-chip {
    display:inline-flex; align-items:center; gap:4px;
    padding:2px 8px; border-radius:10px; font-size:11px; font-weight:500;
    background:var(--surface2); transition:all 0.2s;
  }
  .approval-chip.approved { background:#1a3a2a; }
  .approval-chip .check { color:var(--green); font-weight:700; }
  .btn-approve:disabled,.btn-reject:disabled { opacity:0.4; cursor:not-allowed; }

  /* ---- Toasts ---- */
  .toast-container { position:fixed; top:16px; right:16px; z-index:1000; display:flex; flex-direction:column; gap:8px; }
  .toast {
    padding:10px 16px; border-radius:6px; font-size:13px;
    animation:slideIn 0.3s ease; box-shadow:0 4px 12px rgba(0,0,0,0.4);
  }
  .toast-info { background:#1f3a5f; color:var(--accent); }
  .toast-success { background:#1a3a2a; color:var(--green); }
  .toast-error { background:#3d1f1f; color:var(--red); }
  @keyframes slideIn { from{transform:translateX(100%);opacity:0}to{transform:none;opacity:1} }

  /* ---- Closing Overlay ---- */
  .closing-overlay {
    position:fixed; inset:0; z-index:2000;
    background:rgba(0,0,0,0.85); display:flex;
    flex-direction:column; align-items:center; justify-content:center;
    animation:fadeIn 0.3s ease;
  }
  .closing-overlay h2 {
    color:var(--green); font-size:28px; margin:0 0 12px;
    font-weight:700;
  }
  .closing-overlay p {
    color:var(--fg); font-size:16px; margin:0;
    opacity:0.8;
  }
  @keyframes fadeIn { from{opacity:0}to{opacity:1} }

  /* ---- Username modal ---- */
  .modal-overlay {
    position:fixed; top:0; left:0; width:100%; height:100%;
    background:rgba(0,0,0,0.6); z-index:2000;
    display:flex; align-items:center; justify-content:center;
  }
  .modal {
    background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); padding:28px; width:380px;
    box-shadow:0 12px 40px rgba(0,0,0,0.5);
  }
  .modal h2 { font-size:16px; margin-bottom:4px; }
  .modal p { font-size:13px; color:var(--text-dim); margin-bottom:16px; }
  .modal input {
    width:100%; background:var(--bg); border:1px solid var(--border); color:var(--text);
    padding:10px 14px; border-radius:6px; font-size:14px; margin-bottom:14px; outline:none;
  }
  .modal input:focus { border-color:var(--accent); }
  .modal button {
    width:100%; background:var(--accent); color:var(--bg); border:none;
    padding:10px; border-radius:6px; cursor:pointer; font-size:14px; font-weight:600;
  }

  .hidden { display:none !important; }

  /* ---- Responsive ---- */
  @media (max-width:900px) {
    .layout { flex-direction:column; }
    .sidebar-col { width:100%; max-height:none; position:static; border-left:none; border-top:1px solid var(--border); }
  }
</style>
</head>
<body>
<div class="top-bar"></div>

<div id="username-modal" class="modal-overlay">
  <div class="modal">
    <h2>Join Plan Review</h2>
    <p>Enter your name to collaborate on this plan</p>
    <input type="text" id="username-input" placeholder="Your name..." autofocus>
    <button onclick="setUsername()">Join</button>
  </div>
</div>

<div class="toast-container" id="toasts"></div>

<div id="app" style="display:none">
<div class="layout">
  <div class="main-col">
    <div class="header">
      <div class="header-left">
        <span class="logo">MINI CLAUDE CODE</span>
        <h1>Plan Review</h1>
      </div>
      <span class="status status-draft" id="plan-status">DRAFT</span>
    </div>

    <div class="online-bar">
      <span class="pulse-dot"></span>
      <span id="user-count">0</span> online
      <span id="user-badges"></span>
    </div>

    <div class="document" id="editor" contenteditable="true"></div>

    <!-- Selection toolbar (positioned absolutely) -->
    <div class="sel-toolbar" id="sel-toolbar">
      <button class="tb-annotate" onclick="onToolbarAnnotate()">Annotate</button>
      <div class="sel-toolbar-sep"></div>
      <button class="tb-delete" onclick="onToolbarDelete()">Delete</button>
      <div class="sel-toolbar-sep"></div>
      <button class="tb-addtext" onclick="onToolbarAddText()">Add Text</button>
    </div>

    <!-- Annotation input popover -->
    <div class="ann-popover" id="ann-popover">
      <textarea id="ann-text" placeholder="Write your annotation..."></textarea>
      <div class="ann-actions">
        <button class="btn-cancel" onclick="hideAnnPopover()">Cancel</button>
        <button class="btn-save" onclick="saveAnnotation()">Add</button>
      </div>
    </div>

    <div class="approval-bar" id="approval-bar">
      <div style="display:flex;flex-direction:column;gap:8px;flex:1">
        <div class="info" id="approval-info">Review, edit, and annotate the plan. Approve when ready.</div>
        <div class="approval-status" id="approval-status"></div>
      </div>
      <div class="approval-buttons">
        <button class="btn-reject" onclick="rejectPlan()" id="btn-reject">Reject</button>
        <button class="btn-request-changes" onclick="requestChanges()" id="btn-request-changes">Request Changes</button>
        <button class="btn-approve" onclick="approvePlan()" id="btn-approve">Approve Plan</button>
      </div>
    </div>
  </div>

  <div class="sidebar-col">
    <div class="sidebar-title">Annotations</div>
    <div id="ann-list"></div>

    <div class="history-toggle" onclick="toggleHistory()">
      Edit History <span id="history-count"></span>
    </div>
    <div class="history-list" id="history-list"></div>
  </div>
</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.1/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-typescript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-rust.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-go.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/turndown/7.2.0/turndown.min.js"></script>

<script>
// --- Turndown: HTML -> Markdown converter ---
const turndownService = new TurndownService({
  headingStyle: 'atx',
  codeBlockStyle: 'fenced',
  bulletListMarker: '-',
  emDelimiter: '*',
  strongDelimiter: '**',
});
// Preserve language class on fenced code blocks
turndownService.addRule('fencedCodeBlock', {
  filter: function (node, options) {
    return node.nodeName === 'PRE' && node.firstChild && node.firstChild.nodeName === 'CODE';
  },
  replacement: function (content, node) {
    const code = node.firstChild;
    const lang = (code.className || '').replace(/^language-/, '').split(' ')[0] || '';
    const text = code.textContent || '';
    return '\n\n```' + lang + '\n' + text.replace(/\n$/, '') + '\n```\n\n';
  }
});
// Strip <mark> annotation wrappers (they're not part of the source content)
turndownService.addRule('stripAnnotationMarks', {
  filter: function (node) {
    return node.nodeName === 'MARK' && node.classList.contains('annotation');
  },
  replacement: function (content) { return content; }
});
// Strip tracked <ins>/<del> tags — preserve their text content
turndownService.addRule('stripTrackedIns', {
  filter: function (node) { return node.nodeName === 'INS' && node.classList.contains('tracked'); },
  replacement: function (content) { return content; }
});
turndownService.addRule('stripTrackedDel', {
  filter: function (node) { return node.nodeName === 'DEL' && node.classList.contains('tracked'); },
  replacement: function () { return ''; }
});

// --- Per-user color palette ---
const USER_COLORS = [
  '#58a6ff', '#f0883e', '#bc8cff', '#3fb950',
  '#f85149', '#d2a8ff', '#79c0ff', '#e3b341',
];
const userColorMap = {};
function getUserColor(user) {
  if (!userColorMap[user]) {
    const idx = Object.keys(userColorMap).length % USER_COLORS.length;
    userColorMap[user] = USER_COLORS[idx];
  }
  return userColorMap[user];
}
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return 'rgba('+r+','+g+','+b+','+alpha+')';
}

// --- State ---
let plan = null;
let username = '';
let ws = null;
let onlineUsers = new Set();
let pendingAnnRange = null;  // {start, end, quote} while annotation popover is open
let editDebounce = null;
let suppressSync = false;    // prevent echo loops when receiving remote edits
let approvalState = { approved: new Set(), connected: new Set(), allApproved: false };

// --- Init ---
document.getElementById('username-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') setUsername();
});

function setUsername() {
  const input = document.getElementById('username-input');
  username = input.value.trim() || ('user-' + Math.random().toString(36).slice(2, 6));
  document.getElementById('username-modal').classList.add('hidden');
  document.getElementById('app').style.display = 'block';
  connectWebSocket();
  fetchPlan();
}

// --- WebSocket ---
function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws?user=' + encodeURIComponent(username));
  ws.onopen = () => toast('Connected', 'info');
  ws.onclose = () => { toast('Disconnected. Reconnecting...', 'error'); setTimeout(connectWebSocket, 2000); };
  ws.onmessage = e => handleWsMsg(JSON.parse(e.data));
}
function sendWs(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); }

function handleWsMsg(msg) {
  switch (msg.type) {
    case 'plan_update':
      plan = msg.plan;
      renderDocument();
      renderAnnotations();
      renderHistory();
      updateStatus();
      break;
    case 'content_update':
      if (plan && msg.user !== username) {
        plan.content = msg.content;
        if (msg.edit) plan.edit_history.push(msg.edit);
        suppressSync = true;
        renderDocument();
        suppressSync = false;
        renderHistory();
      }
      break;
    case 'annotation_add':
      if (plan) {
        plan.annotations.push(msg.annotation);
        renderDocument();
        renderAnnotations();
      }
      break;
    case 'annotation_resolve':
      if (plan) {
        const a = plan.annotations.find(x => x.id === msg.annotation_id);
        if (a) a.resolved = true;
        renderAnnotations();
      }
      break;
    case 'user_join':
      onlineUsers.add(msg.user); updateOnlineUsers();
      toast(msg.user + ' joined', 'info');
      break;
    case 'user_leave':
      onlineUsers.delete(msg.user); updateOnlineUsers();
      break;
    case 'users_list':
      onlineUsers = new Set(msg.users); updateOnlineUsers();
      break;
    case 'user_approved':
      if (msg.status) syncApprovalState(msg.status);
      toast(msg.user + ' approved (' + approvalState.approved.size + '/' + approvalState.connected.size + ')', 'success');
      break;
    case 'all_approved':
      approvalState.allApproved = true;
      if (msg.approved_by) msg.approved_by.forEach(u => approvalState.approved.add(u));
      if (plan) { plan.status = 'approved'; plan.approved_by = msg.approved_by || []; }
      updateStatus(); disableEditing(); renderApprovalStatus();
      toast('All reviewers approved! Plan will now execute.', 'success');
      break;
    case 'approval_status':
      if (msg.status) syncApprovalState(msg.status);
      break;
    case 'rejected':
      if (plan) { plan.status = 'rejected'; plan.rejection_reason = msg.reason || ''; }
      updateStatus(); disableEditing();
      toast('Plan rejected by ' + msg.user + (msg.reason ? ': '+msg.reason : ''), 'error');
      break;
    case 'changes_requested':
      if (plan) { plan.status = 'changes_requested'; }
      if (msg.annotation && plan) {
        plan.annotations.push(msg.annotation);
        renderDocument();
        renderAnnotations();
      }
      updateStatus();
      toast('Changes requested by ' + msg.user + (msg.reason ? ': '+msg.reason : '') + '. Edit the plan and approve when ready.', 'info');
      break;
  }
}

function syncApprovalState(status) {
  approvalState.approved = new Set(status.approved_users || []);
  approvalState.connected = new Set(status.connected_users || []);
  approvalState.allApproved = !!status.all_approved;
  renderApprovalStatus();
  // Disable approve button if this user already approved
  if (approvalState.approved.has(username)) {
    const btn = document.getElementById('btn-approve');
    btn.textContent = 'You Approved';
    btn.disabled = true;
  }
}

function renderApprovalStatus() {
  const el = document.getElementById('approval-status');
  if (!el) return;
  const count = approvalState.approved.size;
  const total = approvalState.connected.size;
  let html = '<span class="approval-count">' + count + '/' + total + ' approved</span> ';
  for (const user of approvalState.connected) {
    const approved = approvalState.approved.has(user);
    const color = getUserColor(user);
    html += '<span class="approval-chip' + (approved ? ' approved' : '') + '" style="color:' + color + ';border:1px solid ' + color + '">';
    if (approved) html += '<span class="check">&#10003;</span> ';
    html += esc(user) + '</span> ';
  }
  el.innerHTML = html;
}

// --- API ---
async function fetchPlan() {
  const resp = await fetch('/api/plan');
  plan = await resp.json();
  renderDocument();
  renderAnnotations();
  renderHistory();
  updateStatus();
}

// --- Rendering ---
function renderDocument() {
  const editor = document.getElementById('editor');
  if (!plan) return;

  // Render markdown to HTML
  let html = marked.parse(plan.content || '', { breaks: true });

  // Apply annotation highlights (must be done on rendered HTML — approximate via text matching)
  const activeAnns = (plan.annotations || []).filter(a => !a.resolved && a.quote);
  for (const ann of activeAnns) {
    const escaped = escapeRegex(ann.quote);
    const annColor = getUserColor(ann.user);
    const markStyle = 'style="background:'+hexToRgba(annColor,0.15)+';border-bottom-color:'+annColor+'"';
    try {
      const re = new RegExp('(?<=>)([^<]*?)(' + escaped + ')([^<]*?)(?=<)', 'g');
      html = html.replace(re, (m, pre, match, post) =>
        '>' + pre + '<mark class="annotation" data-ann-id="' + ann.id + '" '+markStyle+'>' + match + '</mark>' + post + '<'
      );
    } catch(e) {
      html = html.replace(ann.quote,
        '<mark class="annotation" data-ann-id="' + ann.id + '" '+markStyle+'>' + ann.quote + '</mark>');
    }
  }

  editor.innerHTML = html;

  // Syntax highlight code blocks
  editor.querySelectorAll('pre code').forEach(el => {
    try { Prism.highlightElement(el); } catch(e) {}
  });
}

function updateStatus() {
  if (!plan) return;
  const el = document.getElementById('plan-status');
  const displayStatus = plan.status === 'changes_requested' ? 'CHANGES REQUESTED' : plan.status.toUpperCase();
  el.textContent = displayStatus;
  el.className = 'status status-' + plan.status;
  const locked = plan.status === 'approved' || plan.status === 'rejected';
  document.getElementById('btn-reject').disabled = locked;
  document.getElementById('btn-request-changes').disabled = locked;
  // Don't re-enable approve if user already approved
  if (locked || approvalState.approved.has(username)) {
    document.getElementById('btn-approve').disabled = true;
  } else {
    document.getElementById('btn-approve').disabled = false;
  }
  if (plan.status === 'approved') {
    const approvers = Array.isArray(plan.approved_by) ? plan.approved_by.join(', ') : (plan.approved_by || 'unknown');
    document.getElementById('approval-info').textContent =
      'Plan approved by ' + approvers + '. The agent will now execute it.';
  } else if (plan.status === 'rejected') {
    document.getElementById('approval-info').textContent =
      'Plan rejected' + (plan.rejection_reason ? ': ' + plan.rejection_reason : '') + '. The plan has been abandoned.';
  } else if (plan.status === 'changes_requested') {
    document.getElementById('approval-info').textContent =
      'Changes have been requested. Edit the plan above and approve when ready.';
  }
  if (locked) disableEditing();
}

function disableEditing() {
  document.getElementById('editor').contentEditable = 'false';
}

function renderAnnotations() {
  const list = document.getElementById('ann-list');
  if (!plan || !plan.annotations) { list.innerHTML = ''; return; }
  const sorted = [...plan.annotations].sort((a,b) => a.range_start - b.range_start);
  list.innerHTML = sorted.map(a => `
    <div class="ann-card ${a.resolved ? 'resolved' : ''} ${pendingAnnRange && false ? 'active' : ''}"
         data-ann-id="${a.id}" onclick="focusAnnotation('${a.id}')">
      <div class="ann-card-user" style="color:${getUserColor(a.user)}">@${esc(a.user)}</div>
      ${a.quote ? '<div class="ann-card-quote">"' + esc(a.quote.slice(0,80)) + (a.quote.length>80?'...':'') + '"</div>' : ''}
      <div class="ann-card-text">${esc(a.text)}</div>
      <div class="ann-card-time">${fmtTime(a.created_at)}</div>
      ${!a.resolved ? '<div class="ann-card-resolve" onclick="event.stopPropagation();resolveAnnotation(\''+a.id+'\')">Resolve</div>' : ''}
    </div>
  `).join('');
}

function renderHistory() {
  const list = document.getElementById('history-list');
  const count = document.getElementById('history-count');
  if (!plan || !plan.edit_history) { list.innerHTML = ''; count.textContent = ''; return; }
  count.textContent = '(' + plan.edit_history.length + ')';
  // Show most recent first, limit to 50
  const recent = plan.edit_history.slice(-50).reverse();
  list.innerHTML = recent.map(e => {
    const typeClass = 'edit-type-' + e.edit_type;
    const label = e.edit_type === 'insert' ? 'added text' :
                  e.edit_type === 'delete' ? 'deleted text' : 'edited';
    const preview = (e.new_text || e.old_text || '').slice(0, 40);
    return `<div class="edit-entry">
      <span class="edit-user" style="color:${getUserColor(e.user)}">@${esc(e.user)}</span>
      <span class="${typeClass}">${label}</span>
      ${preview ? ' <span style="color:var(--text-faint)">"'+esc(preview)+'"</span>' : ''}
      <span style="float:right">${fmtTime(e.created_at)}</span>
    </div>`;
  }).join('');
}

function toggleHistory() {
  document.getElementById('history-list').classList.toggle('visible');
}

function updateOnlineUsers() {
  document.getElementById('user-count').textContent = onlineUsers.size;
  document.getElementById('user-badges').innerHTML =
    Array.from(onlineUsers).map(u => {
      const c = getUserColor(u);
      return '<span class="user-chip" style="color:'+c+';border:1px solid '+c+'">' + esc(u) + '</span>';
    }).join(' ');
}

// --- Editor: content change tracking ---
document.addEventListener('DOMContentLoaded', () => {
  const editor = document.getElementById('editor');

  editor.addEventListener('input', () => {
    if (suppressSync || !plan) return;
    clearTimeout(editDebounce);
    editDebounce = setTimeout(() => {
      // Extract plain text content to get the new "source" markdown
      // We treat the edited innerHTML as the new content
      const newContent = extractMarkdownFromEditor();
      if (newContent === plan.content) return;
      const edit = {
        id: rndId(), user: username, edit_type: 'replace',
        offset: 0, old_text: '', new_text: '',
        created_at: new Date().toISOString()
      };
      plan.content = newContent;
      plan.edit_history.push(edit);
      sendWs({type: 'content_update', content: newContent, user: username, edit: edit});
      renderHistory();
    }, 600);
  });
});

function extractMarkdownFromEditor() {
  const editor = document.getElementById('editor');
  // Convert the edited HTML back to markdown using Turndown
  // This preserves headings, bold, code blocks, lists, etc.
  return turndownService.turndown(editor.innerHTML);
}

// --- Selection toolbar ---
document.addEventListener('mouseup', e => {
  const toolbar = document.getElementById('sel-toolbar');
  const editor = document.getElementById('editor');
  if (plan && (plan.status === 'approved' || plan.status === 'rejected')) {
    toolbar.classList.remove('visible');
    return;
  }
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) {
    toolbar.classList.remove('visible');
    return;
  }
  // Only show if selection is within the editor
  const range = sel.getRangeAt(0);
  if (!editor.contains(range.commonAncestorContainer)) {
    toolbar.classList.remove('visible');
    return;
  }
  const rect = range.getBoundingClientRect();
  const editorRect = editor.getBoundingClientRect();
  toolbar.style.top = (rect.top - editorRect.top - 44 + editor.offsetTop) + 'px';
  toolbar.style.left = (rect.left - editorRect.left + rect.width/2 - 80 + editor.offsetLeft) + 'px';
  toolbar.classList.add('visible');
});

document.addEventListener('mousedown', e => {
  const toolbar = document.getElementById('sel-toolbar');
  if (!toolbar.contains(e.target)) toolbar.classList.remove('visible');
});

// --- Toolbar actions ---
function getSelectionInfo() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0);
  const text = sel.toString();
  // Compute approximate char offset in the plain text
  const editor = document.getElementById('editor');
  const fullText = editor.innerText || '';
  const start = fullText.indexOf(text);
  return { range, text, start: start >= 0 ? start : 0, end: (start >= 0 ? start : 0) + text.length };
}

function onToolbarDelete() {
  const info = getSelectionInfo();
  if (!info || !plan) return;
  const range = info.range;
  // Wrap in <del> with per-user color
  const color = getUserColor(username);
  const del = document.createElement('del');
  del.className = 'tracked';
  del.setAttribute('data-info', 'Deleted by @' + username);
  del.setAttribute('data-user', username);
  del.style.color = color;
  del.style.textDecorationColor = color;
  del.style.background = hexToRgba(color, 0.12);
  try {
    range.surroundContents(del);
  } catch(e) {
    // If range spans multiple elements, use extractContents
    const frag = range.extractContents();
    del.appendChild(frag);
    range.insertNode(del);
  }
  document.getElementById('sel-toolbar').classList.remove('visible');
  window.getSelection().removeAllRanges();
  // Record edit
  const edit = {
    id: rndId(), user: username, edit_type: 'delete',
    offset: info.start, old_text: info.text, new_text: '',
    created_at: new Date().toISOString()
  };
  if (plan) {
    plan.edit_history.push(edit);
    plan.content = extractMarkdownFromEditor();
    sendWs({type: 'content_update', content: plan.content, user: username, edit: edit});
    renderHistory();
  }
}

function onToolbarAddText() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !plan) return;
  const range = sel.getRangeAt(0);
  const newText = prompt('Enter text to add:');
  if (!newText) return;
  const insColor = getUserColor(username);
  const ins = document.createElement('ins');
  ins.className = 'tracked';
  ins.setAttribute('data-info', 'Added by @' + username);
  ins.setAttribute('data-user', username);
  ins.style.borderBottomColor = insColor;
  ins.style.background = hexToRgba(insColor, 0.12);
  ins.textContent = newText;
  range.deleteContents();
  range.insertNode(ins);
  document.getElementById('sel-toolbar').classList.remove('visible');
  window.getSelection().removeAllRanges();
  const edit = {
    id: rndId(), user: username, edit_type: 'insert',
    offset: 0, old_text: '', new_text: newText,
    created_at: new Date().toISOString()
  };
  plan.edit_history.push(edit);
  plan.content = extractMarkdownFromEditor();
  sendWs({type: 'content_update', content: plan.content, user: username, edit: edit});
  renderHistory();
}

function onToolbarAnnotate() {
  const info = getSelectionInfo();
  if (!info) return;
  pendingAnnRange = { start: info.start, end: info.end, quote: info.text };
  const toolbar = document.getElementById('sel-toolbar');
  const popover = document.getElementById('ann-popover');
  popover.style.top = toolbar.style.top;
  popover.style.left = toolbar.style.left;
  popover.classList.add('visible');
  toolbar.classList.remove('visible');
  document.getElementById('ann-text').value = '';
  document.getElementById('ann-text').focus();
  window.getSelection().removeAllRanges();
}

function hideAnnPopover() {
  document.getElementById('ann-popover').classList.remove('visible');
  pendingAnnRange = null;
}

function saveAnnotation() {
  if (!pendingAnnRange || !plan) return;
  const text = document.getElementById('ann-text').value.trim();
  if (!text) return;
  const ann = {
    id: rndId(), user: username, text: text,
    quote: pendingAnnRange.quote,
    range_start: pendingAnnRange.start,
    range_end: pendingAnnRange.end,
    resolved: false,
    created_at: new Date().toISOString()
  };
  plan.annotations.push(ann);
  sendWs({type: 'annotation_add', annotation: ann, user: username});
  hideAnnPopover();
  renderDocument();
  renderAnnotations();
}

function focusAnnotation(annId) {
  // Highlight the annotation in the document
  document.querySelectorAll('mark.annotation').forEach(el => el.classList.remove('active'));
  const mark = document.querySelector('mark.annotation[data-ann-id="'+annId+'"]');
  if (mark) {
    mark.classList.add('active');
    mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  // Highlight sidebar card
  document.querySelectorAll('.ann-card').forEach(el => el.classList.remove('active'));
  const card = document.querySelector('.ann-card[data-ann-id="'+annId+'"]');
  if (card) card.classList.add('active');
}

function resolveAnnotation(annId) {
  if (!plan) return;
  const ann = plan.annotations.find(a => a.id === annId);
  if (ann) ann.resolved = true;
  sendWs({type: 'annotation_resolve', annotation_id: annId, user: username});
  renderAnnotations();
  renderDocument();
}

// --- Closing Overlay ---
function showClosingOverlay() {
  const overlay = document.createElement('div');
  overlay.className = 'closing-overlay';
  overlay.innerHTML = '<h2>Your plan is submitted</h2><p id="closing-countdown">Closing tab in 5 seconds...</p>';
  document.body.appendChild(overlay);
  let remaining = 5;
  const interval = setInterval(() => {
    remaining--;
    const el = document.getElementById('closing-countdown');
    if (remaining > 0) {
      el.textContent = 'Closing tab in ' + remaining + ' second' + (remaining !== 1 ? 's' : '') + '...';
    } else {
      clearInterval(interval);
      el.textContent = 'Closing tab...';
      try { window.close(); } catch(e) {}
      setTimeout(() => {
        el.textContent = 'You can safely close this tab.';
      }, 500);
    }
  }, 1000);
}

// --- Approve / Request Changes / Reject ---
function approvePlan() {
  if (!confirm('Approve this plan?')) return;
  sendWs({type: 'approve', user: username});
  const btn = document.getElementById('btn-approve');
  btn.textContent = 'You Approved';
  btn.disabled = true;
  showClosingOverlay();
}

function requestChanges() {
  const reason = prompt('What changes would you like? (optional):') || '';
  sendWs({type: 'request_changes', user: username, reason: reason});
}

function rejectPlan() {
  if (!confirm('Reject this plan entirely? The plan will be abandoned and the flow will end.')) return;
  const reason = prompt('Reason for rejection (optional):') || '';
  sendWs({type: 'rejected', user: username, reason: reason});
}

// --- Utils ---
function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function fmtTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); }
  catch { return ''; }
}
function rndId() { return Math.random().toString(36).slice(2,10); }
function toast(msg, type='info') {
  const c = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast toast-'+type; el.textContent = msg;
  c.appendChild(el); setTimeout(() => el.remove(), 4000);
}
</script>
</body>
</html>"""
