"""Standalone admin/debug page for inspecting tasks and skill beliefs.

Served at /admin as a self-contained HTML page. Requires authentication.
There is no knowledge graph: tasks carry plain-English ``context_notes``.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

admin_page_router = APIRouter(tags=["admin-page"])

_ADMIN_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Research Coach — Debug UI</title>
<style>
:root {
  --bg: #0f1117;
  --bg2: #1a1d27;
  --bg3: #242836;
  --border: #2e3347;
  --text: #e2e4ed;
  --text-muted: #8b8fa3;
  --accent: #6366f1;
  --success: #22c55e;
  --warning: #f59e0b;
  --error: #ef4444;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace; background: var(--bg); color: var(--text); font-size: 13px; }
.header { display: flex; align-items: center; justify-content: space-between; padding: 10px 20px; border-bottom: 1px solid var(--border); background: var(--bg2); }
.header h1 { font-size: 14px; font-weight: 600; }
.header-controls { display: flex; gap: 10px; align-items: center; }
select, button { font-family: inherit; font-size: 12px; padding: 5px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg3); color: var(--text); cursor: pointer; }
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); border-color: var(--accent); color: white; }
button.danger { background: #ef444420; border-color: var(--error); color: var(--error); }
button.danger:disabled { opacity: 0.4; cursor: not-allowed; }
button:disabled { opacity: 0.4; cursor: not-allowed; }
input, textarea { font-family: inherit; font-size: 12px; padding: 5px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg3); color: var(--text); }
.stats-bar { display: flex; gap: 16px; padding: 8px 20px; border-bottom: 1px solid var(--border); background: var(--bg2); font-size: 11px; color: var(--text-muted); }
.stats-bar span b { color: var(--text); }
.main { display: block; height: calc(100vh - 85px); overflow: auto; }
.tabs { display: flex; gap: 2px; padding: 8px 16px 0; background: var(--bg2); border-bottom: 1px solid var(--border); }
.tab { padding: 6px 12px; font-size: 11px; font-weight: 500; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.15s; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-content { display: none; }
.tab-content.active { display: block; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; position: sticky; top: 0; background: var(--bg); }
td { padding: 5px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:hover td { background: var(--bg3); }
.bar-wrap { width: 80px; height: 6px; background: var(--bg3); border-radius: 3px; display: inline-block; vertical-align: middle; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.bar-mastery { background: var(--success); }
.panel-body { padding: 12px 16px; }
.empty { text-align: center; padding: 40px 20px; color: var(--text-muted); }
.empty p { margin-top: 8px; font-size: 12px; }
.error-msg { background: #ef444420; color: var(--error); padding: 10px 16px; border-radius: 6px; margin: 12px 16px; font-size: 12px; }
.meta { font-size: 11px; color: var(--text-muted); }
.context-cell { max-width: 320px; white-space: pre-wrap; }
</style>
</head>
<body>

<div class="header">
  <h1>AI Research Coach — Debug UI</h1>
  <div class="header-controls">
    <select id="candidate-select"><option value="">Select candidate...</option></select>
    <button class="primary" onclick="refreshAll()">Refresh</button>
  </div>
</div>
<div class="stats-bar" id="stats-bar">Loading stats...</div>

<div class="main">
  <div class="tabs" id="main-tabs">
    <div class="tab active" data-tab="questions">Questions</div>
    <div class="tab" data-tab="skillstates">SkillState</div>
    <div class="tab" data-tab="sessions">Sessions</div>
  </div>
  <div style="padding:12px 16px;">
    <div id="tab-questions" class="tab-content active">
        <div class="panel-body">
          <h3 style="font-size:12px;margin-bottom:8px">Questions</h3>
          <div class="meta" style="margin-bottom:8px">Each question carries plain-English context notes (prerequisites, confusions). Edit them inline — no knowledge graph.</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
            <input id="manage-q" placeholder="search prompt…" style="flex:2;min-width:140px">
            <input id="manage-owner" placeholder="owner email…" style="flex:1;min-width:120px">
            <input id="manage-skill" placeholder="skill…" style="flex:1;min-width:80px">
            <button onclick="loadManageTasks()">Search</button>
          </div>
          <div id="manage-tasks"><div class="empty"><p>Loading questions…</p></div></div>
        </div>
    </div>
    <div id="tab-skillstates" class="tab-content"></div>
    <div id="tab-sessions" class="tab-content">
        <div class="panel-body">
          <h3 style="font-size:12px;margin-bottom:8px">Candidate data</h3>
          <div id="manage-summary"><div class="empty"><p>Select a candidate to preview their stored rows</p></div></div>
          <button id="manage-wipe-btn" class="danger" onclick="wipeCandidate()" style="margin-top:8px" disabled>Wipe candidate data</button>
          <div class="meta" style="margin-top:4px">Deletes sessions, attempts, skill beliefs and owned questions. Back up <span style="font-family:inherit">data/coach.db</span> first — this cannot be undone.</div>
        </div>
    </div>
    </div>
</div>

<script>
const TOKEN_KEY = 'ai_coach_token';
function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } }

async function api(path) {
  const token = getToken();
  const headers = {};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch('/admin' + path, { headers });
  if (res.status === 401) {
    document.body.innerHTML = '<div class="empty" style="padding:80px"><h2>Authentication Required</h2><p>Please log in first, then return to this page.</p></div>';
    throw new Error('Unauthorized');
  }
  if (!res.ok) throw new Error('API error ' + res.status);
  return res.json();
}

async function apiDelete(path) {
  const token = getToken();
  const headers = {};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch('/admin' + path, { method: 'DELETE', headers });
  if (res.status === 401) {
    document.body.innerHTML = '<div class="empty" style="padding:80px"><h2>Authentication Required</h2><p>Please log in first, then return to this page.</p></div>';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    let detail = 'API error ' + res.status;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

async function apiPatch(path, body) {
  const token = getToken();
  const headers = {'Content-Type': 'application/json'};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch('/admin' + path, { method: 'PATCH', headers, body: JSON.stringify(body) });
  if (!res.ok) {
    let detail = 'API error ' + res.status;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Tab switching
document.querySelectorAll('#main-tabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#main-tabs .tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

// --- Stats ---
async function loadStats() {
  try {
    const s = await api('/stats');
    document.getElementById('stats-bar').innerHTML =
      '<span>Questions: <b>' + s.tasks_total + '</b></span>' +
      '<span>Attempts: <b>' + s.task_attempts + '</b></span>' +
      '<span>Skill beliefs: <b>' + s.skill_beliefs + '</b></span>' +
      '<span>Sessions: <b>' + s.active_sessions + '</b></span>';
  } catch { document.getElementById('stats-bar').textContent = 'Failed to load stats'; }
}

// --- Candidate list ---
async function loadCandidates() {
  try {
    const data = await api('/learners');
    const sel = document.getElementById('candidate-select');
    sel.innerHTML = '<option value="">Select candidate...</option>';
    data.learners.forEach(l => {
      const opt = document.createElement('option');
      opt.value = l.candidate;
      opt.textContent = l.candidate;
      sel.appendChild(opt);
    });
  } catch {}
}

async function renderSkillStates() {
  const el = document.getElementById('tab-skillstates');
  const candidate = document.getElementById('candidate-select').value;
  if (!candidate) { el.innerHTML = '<div class="empty"><p>Select a candidate to view SkillState</p></div>'; return; }
  try {
    const data = await api('/skill-states/' + encodeURIComponent(candidate));
    if (!data.skill_states || !Object.keys(data.skill_states).length) {
      el.innerHTML = '<div class="empty"><p>No SkillState data (no active session)</p></div>';
      return;
    }
    let html = '<div class="panel-body"><div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">Source: '+data.source+'</div>';
    html += '<table><thead><tr><th>Skill</th><th>Score</th><th>Variance</th><th>Confidence</th><th>Questions</th><th></th></tr></thead><tbody>';
    for (const [skill, s] of Object.entries(data.skill_states)) {
      const confPct = (s.confidence * 100).toFixed(0);
      const scorePct = (s.score * 100).toFixed(0);
      html += '<tr><td><b>'+esc(skill)+'</b></td><td>'+scorePct+'%</td><td>'+s.variance.toFixed(4)+'</td><td>'+confPct+'%</td><td>'+s.questions_answered+'</td><td><span class="bar-wrap" style="width:120px"><span class="bar-fill bar-mastery" style="width:'+scorePct+'%"></span></span></td></tr>';
    }
    html += '</tbody></table></div>';
    el.innerHTML = html;
  } catch { el.innerHTML = '<div class="error-msg">Failed to load SkillState</div>'; }
}

// --- Manage (wipes + question deletes + context edits) ---
const SUMMARY_LABELS = [
  ['active_sessions', 'Sessions'],
  ['task_attempts', 'Attempts'],
  ['skill_beliefs', 'Skill beliefs'],
  ['owned_tasks', 'Owned questions'],
];

async function loadCandidateSummary() {
  const candidate = document.getElementById('candidate-select').value;
  const el = document.getElementById('manage-summary');
  const btn = document.getElementById('manage-wipe-btn');
  if (!candidate) {
    el.innerHTML = '<div class="empty"><p>Select a candidate to preview their stored rows</p></div>';
    btn.disabled = true;
    return;
  }
  try {
    const s = await api('/candidate/' + encodeURIComponent(candidate) + '/summary');
    let html = '<table><thead><tr><th>Table</th><th>Rows</th></tr></thead><tbody>';
    SUMMARY_LABELS.forEach(([key, label]) => {
      html += '<tr><td>' + label + '</td><td><b>' + (s[key] || 0) + '</b></td></tr>';
    });
    html += '<tr><td><b>Total</b></td><td><b>' + (s.total || 0) + '</b></td></tr></tbody></table>';
    el.innerHTML = html;
    btn.disabled = (s.total || 0) === 0;
  } catch (e) {
    el.innerHTML = '<div class="error-msg">' + esc(e.message) + '</div>';
    btn.disabled = true;
  }
}

async function wipeCandidate() {
  const candidate = document.getElementById('candidate-select').value;
  if (!candidate) return;
  let total = '?';
  try {
    const s = await api('/candidate/' + encodeURIComponent(candidate) + '/summary');
    total = s.total;
  } catch {}
  if (!confirm('Delete ALL ' + total + ' stored rows for ' + candidate + '?\nSessions, attempts, skill beliefs and owned questions.\nThis cannot be undone.')) return;
  try {
    const r = await apiDelete('/candidate/' + encodeURIComponent(candidate));
    alert('Wiped ' + (r.deleted && r.deleted.total != null ? r.deleted.total : '?') + ' rows for ' + candidate + '.');
    await refreshAll();
  } catch (e) {
    alert('Wipe failed: ' + e.message);
  }
}

async function loadManageTasks() {
  const el = document.getElementById('manage-tasks');
  const q = document.getElementById('manage-q').value.trim();
  const owner = document.getElementById('manage-owner').value.trim();
  const skill = document.getElementById('manage-skill').value.trim();
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (owner) params.set('owner', owner);
  if (skill) params.set('skill', skill);
  params.set('limit', '200');
  try {
    const data = await api('/tasks?' + params.toString());
    if (!data.tasks.length) { el.innerHTML = '<div class="empty"><p>No questions match</p></div>'; return; }
    let html = '<table><thead><tr><th>Prompt</th><th>Skill</th><th>Owner</th><th>Attempts</th><th>Context notes</th><th></th></tr></thead><tbody>';
    data.tasks.forEach(t => {
      const excerpt = esc((t.prompt || '').slice(0, 80)) + ((t.prompt || '').length > 80 ? '…' : '');
      const ctx = esc((t.context_notes || '').slice(0, 160));
      html += '<tr><td title="' + esc(t.prompt || '') + '">' + excerpt + '<br><span style="color:var(--text-muted);font-size:10px">' + esc(t.id) + '</span></td>' +
        '<td>' + esc(t.skill || '') + '</td><td>' + esc(t.owner || '') + '</td><td>' + (t.attempt_count || 0) + '</td>' +
        '<td class="context-cell">' + (ctx || '<span style="color:var(--text-muted)">—</span>') +
        '<br><button onclick="editContext(\'' + t.id.replace(/'/g, "\\'") + '\')">Edit context</button></td>' +
        '<td style="white-space:nowrap"><button class="danger" onclick="deleteTask(\'' + t.id.replace(/'/g, "\\'") + '\',' + (t.attempt_count || 0) + ')">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="error-msg">' + esc(e.message) + '</div>';
  }
}

async function deleteTask(taskId, attempts) {
  if (!confirm('Delete question ' + taskId + ' plus its ' + attempts + ' attempt(s)?\nThis cannot be undone.')) return;
  try {
    await apiDelete('/tasks/' + encodeURIComponent(taskId));
    await loadManageTasks();
    await loadStats();
  } catch (e) {
    alert('Delete failed: ' + e.message);
  }
}

async function editContext(taskId) {
  const current = prompt('Plain-English context notes for ' + taskId + ' (e.g. "A is a prerequisite of B, often confused with C"):', '');
  if (current === null) return;
  try {
    await apiPatch('/tasks/' + encodeURIComponent(taskId), { context_notes: current });
    await loadManageTasks();
  } catch (e) {
    alert('Edit failed: ' + e.message);
  }
}

// --- Refresh ---
async function refreshAll() {
  const candidate = document.getElementById('candidate-select').value;
  await Promise.all([loadStats(), loadManageTasks(), loadCandidateSummary()]);
  await renderSkillStates();
}

document.getElementById('candidate-select').addEventListener('change', () => {
  loadCandidateSummary();
  renderSkillStates();
});

// Init
(async () => {
  await loadStats();
  await loadCandidates();
  await loadManageTasks();
})();
</script>
</body>
</html>"""


@admin_page_router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return HTMLResponse(content=_ADMIN_PAGE_HTML)
