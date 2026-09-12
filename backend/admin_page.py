"""Standalone admin/debug page for inspecting per-task graphs and the learner model.

Served at /admin as a self-contained HTML page with inline SVG graph visualization,
learner model inspector, and SkillState comparison. Requires authentication.
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
  --blue: #3b82f6;
  --green: #22c55e;
  --purple: #a855f7;
  --orange: #f97316;
  --teal: #14b8a6;
  --red: #ef4444;
  --gray: #6b7280;
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
input { font-family: inherit; font-size: 12px; padding: 5px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg3); color: var(--text); }
.stats-bar { display: flex; gap: 16px; padding: 8px 20px; border-bottom: 1px solid var(--border); background: var(--bg2); font-size: 11px; color: var(--text-muted); }
.stats-bar span b { color: var(--text); }
.main { display: block; height: calc(100vh - 85px); overflow: auto; }
.panel { border-right: none; overflow: visible; }
.panel:last-child { border-right: none; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid var(--border); background: var(--bg2); position: sticky; top: 0; z-index: 5; }
.panel-header h2 { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }
.panel-body { padding: 12px 16px; }

/* Tabs */
.tabs { display: flex; gap: 2px; padding: 8px 16px 0; background: var(--bg2); border-bottom: 1px solid var(--border); }
.tab { padding: 6px 12px; font-size: 11px; font-weight: 500; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.15s; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; position: sticky; top: 0; background: var(--bg); }
td { padding: 5px 8px; border-bottom: 1px solid var(--border); }
tr:hover td { background: var(--bg3); }

/* Bars */
.bar-wrap { width: 80px; height: 6px; background: var(--bg3); border-radius: 3px; display: inline-block; vertical-align: middle; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.bar-mastery { background: var(--green); }
.bar-uncertainty { background: var(--warning); }
.bar-priority { background: var(--accent); }
.bar-confidence { background: var(--purple); }

/* Badges */
.badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
.badge-concept { background: #3b82f620; color: var(--blue); }
.badge-skill { background: #22c55e20; color: var(--green); }
.badge-procedure { background: #a855f720; color: var(--purple); }
.badge-problem { background: #f9731620; color: var(--orange); }
.badge-strategy { background: #14b8a620; color: var(--teal); }
.badge-misconception { background: #ef444420; color: var(--red); }
.badge-domain { background: #6b728020; color: var(--gray); }
.badge-mastered { background: #22c55e20; color: var(--green); }
.badge-proficient { background: #3b82f620; color: var(--blue); }
.badge-developing { background: #f59e0b20; color: var(--warning); }
.badge-uncertain { background: #a855f720; color: var(--purple); }
.badge-unknown { background: #6b728020; color: var(--gray); }
.badge-suspected { background: #f59e0b20; color: var(--warning); }
.badge-confirmed { background: #ef444420; color: var(--red); }
.badge-correct { background: #22c55e20; color: var(--green); }
.badge-incorrect { background: #ef444420; color: var(--red); }
.badge-partially_correct { background: #f59e0b20; color: var(--warning); }

/* Task-graph JSON viewer */
.json-view { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; overflow: auto; font-size: 12px; white-space: pre; max-height: 60vh; }
.graph-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.graph-toolbar select { max-width: 320px; }

/* Node detail panel */
.node-detail { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.node-detail h3 { font-size: 13px; margin-bottom: 6px; }
.node-detail .meta { font-size: 11px; color: var(--text-muted); }
.node-detail .connections { margin-top: 8px; font-size: 11px; }
.node-detail .connections li { margin-left: 16px; margin-bottom: 2px; }

/* SkillState comparison */
.comparison-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.comparison-label { font-weight: 600; font-size: 12px; }
.comparison-metric { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

/* Empty state */
.empty { text-align: center; padding: 40px 20px; color: var(--text-muted); }
.empty p { margin-top: 8px; font-size: 12px; }
.error-msg { background: #ef444420; color: var(--error); padding: 10px 16px; border-radius: 6px; margin: 12px 16px; font-size: 12px; }
.loading { text-align: center; padding: 40px; color: var(--text-muted); }

/* Competency mini-bars */
.competency-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.competency-cell { text-align: center; }
.competency-cell .label { font-size: 8px; color: var(--text-muted); }
.competency-cell .bar { width: 100%; height: 4px; background: var(--bg3); border-radius: 2px; margin-top: 2px; }
.competency-cell .fill { height: 100%; border-radius: 2px; background: var(--accent); }
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
    <div class="tab active" data-tab="graph">Task Graph</div>
    <div class="tab" data-tab="states">States</div>
    <div class="tab" data-tab="frontier">Frontier</div>
    <div class="tab" data-tab="misconceptions">Misconceptions</div>
    <div class="tab" data-tab="evidence">Evidence</div>
    <div class="tab" data-tab="skillstates">SkillState</div>
    <div class="tab" data-tab="manage">Manage</div>
  </div>
  <div style="padding:12px 16px;">
    <div id="tab-graph" class="tab-content active">
      <div class="graph-toolbar">
        <select id="graph-task-select"><option value="">Select question…</option></select>
        <span id="graph-info" style="font-size:11px;color:var(--text-muted)"></span>
      </div>
      <div id="graph-json"><div class="empty"><p>No frozen task graphs yet</p></div></div>
    </div>
    <div id="tab-states" class="tab-content"></div>
    <div id="tab-frontier" class="tab-content"></div>
    <div id="tab-misconceptions" class="tab-content"></div>
    <div id="tab-evidence" class="tab-content"></div>
    <div id="tab-skillstates" class="tab-content"></div>
    <div id="tab-manage" class="tab-content">
        <div class="panel-body">
          <h3 style="font-size:12px;margin-bottom:8px">Candidate data</h3>
          <div id="manage-summary"><div class="empty"><p>Select a candidate to preview their stored rows</p></div></div>
          <button id="manage-wipe-btn" class="danger" onclick="wipeCandidate()" style="margin-top:8px" disabled>Wipe candidate data</button>
          <div class="meta" style="margin-top:4px">Deletes sessions, learner rows, attempts, skill beliefs and owned questions. Back up <span style="font-family:inherit">data/coach.db</span> first — this cannot be undone.</div>
          <h3 style="font-size:12px;margin:16px 0 8px">Questions</h3>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
            <input id="manage-q" placeholder="search prompt…" style="flex:2;min-width:140px">
            <input id="manage-owner" placeholder="owner email…" style="flex:1;min-width:120px">
            <input id="manage-skill" placeholder="skill…" style="flex:1;min-width:80px">
            <button onclick="loadManageTasks()">Search</button>
          </div>
          <div id="manage-tasks"><div class="empty"><p>Loading questions…</p></div></div>
          <h3 style="font-size:12px;margin:16px 0 8px">Task graphs</h3>
          <div id="manage-graph-summary"><div class="empty"><p>Loading graph rows…</p></div></div>
          <div style="display:flex;gap:6px;margin-top:8px">
            <button id="manage-graph-rebuild-btn" class="primary" onclick="rebuildGraph()">Rebuild index</button>
          </div>
          <div class="meta" style="margin-top:4px">Graphs live on the questions themselves (frozen at creation). The node/edge index is derived — rebuild re-mirrors every frozen graph without touching learner rows. Admin-only.</div>
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

async function apiPost(path, body) {
  const token = getToken();
  const headers = {'Content-Type': 'application/json'};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch('/admin' + path, { method: 'POST', headers, body: body ? JSON.stringify(body) : undefined });
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
      '<span>Questions: <b>' + s.tasks_total + '</b> (' + s.tasks_frozen + ' frozen)</span>' +
      '<span>Index: <b>' + s.index_nodes + '</b> nodes / <b>' + s.index_edges + '</b> edges</span>' +
      '<span>Learners: <b>' + s.learners + '</b></span>' +
      '<span>States: <b>' + s.knowledge_states + '</b></span>' +
      '<span>Evidence: <b>' + s.evidence_records + '</b></span>' +
      '<span>Misconceptions: <b>' + s.misconceptions + '</b></span>';
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
      opt.textContent = l.candidate + ' (' + l.learner_id.slice(0,8) + '...)';
      sel.appendChild(opt);
    });
  } catch {}
}

// --- Task graph (JSON) ---
let graphTaskId = null;
let learnerData = null;

async function loadGraphList() {
  const sel = document.getElementById('graph-task-select');
  try {
    const data = await api('/graphs');
    const prev = sel.value;
    sel.innerHTML = '<option value="">Select question…</option>';
    data.graphs.forEach(g => {
      const opt = document.createElement('option');
      opt.value = g.task_id;
      opt.textContent = (g.skill || 'general') + ' · ' + g.task_id.slice(0, 18) + ' (' + g.node_count + 'n)';
      sel.appendChild(opt);
    });
    if (data.graphs.some(g => g.task_id === prev)) sel.value = prev;
    if (!sel.value && data.graphs.length) sel.value = data.graphs[0].task_id;
  } catch {
    sel.innerHTML = '<option value="">Failed to load</option>';
  }
}

async function loadGraph() {
  await loadGraphList();
  const sel = document.getElementById('graph-task-select');
  const taskId = sel.value;
  const el = document.getElementById('graph-json');
  const info = document.getElementById('graph-info');
  if (!taskId) {
    graphTaskId = null;
    info.textContent = 'No frozen task graphs yet';
    el.innerHTML = '<div class="empty"><p>No frozen task graphs yet — create a question or run backfill</p></div>';
    return;
  }
  try {
    const data = await api('/tasks/' + encodeURIComponent(taskId) + '/graph');
    if (!data.frozen) {
      graphTaskId = null;
      info.textContent = 'Question has no frozen graph' + (data.error ? ': ' + data.error : '');
      el.innerHTML = '<div class="empty"><p>No frozen graph for this question</p></div>';
      return;
    }
    graphTaskId = data.task_id;
    const g = data.graph;
    info.textContent = taskId.slice(0, 24) + ' · ' + g.nodes.length + ' nodes, ' + (g.edges || []).length + ' edges · primary: ' + g.primary_node_key;
    const payload = { task_id: data.task_id, skill: data.skill, version: g.version, primary_node_key: g.primary_node_key, nodes: g.nodes, edges: g.edges, node_ids: data.node_ids };
    let html = '<div class="json-view">' + esc(JSON.stringify(payload, null, 2)) + '</div>';
    html += '<table style="margin-top:10px"><thead><tr><th>Key</th><th>Type</th><th>Name</th><th>Importance</th><th>Index id</th></tr></thead><tbody>';
    g.nodes.forEach(n => {
      const star = n.key === g.primary_node_key ? ' ★' : '';
      html += '<tr><td><b>' + esc(n.key) + '</b>' + star + '</td><td><span class="badge badge-' + esc(n.type) + '">' + esc(n.type) + '</span></td><td>' + esc(n.name) + '</td><td>' + n.importance + '</td><td style="color:var(--text-muted)">' + esc(((data.node_ids || {})[n.key]) || '—') + '</td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch {
    info.textContent = 'Failed to load';
    el.innerHTML = '<div class="error-msg">Failed to load task graph</div>';
  }
}


// --- Learner data ---
async function loadLearner(candidate) {
  if (!candidate) { learnerData = null; renderTabs(); return; }
  try { learnerData = await api('/learner/' + encodeURIComponent(candidate)); } catch { learnerData = null; }
  renderTabs();
}

function renderTabs() {
  renderStates(); renderFrontier(); renderMisconceptions(); renderEvidence(); renderSkillStates();
}

function bar(val, cls) {
  return '<span class="bar-wrap"><span class="bar-fill ' + cls + '" style="width:' + (val*100) + '%"></span></span> ' + (val*100).toFixed(1) + '%';
}

function renderStates() {
  const el = document.getElementById('tab-states');
  if (!learnerData || !learnerData.states.length) { el.innerHTML = '<div class="empty"><p>No knowledge states yet</p></div>'; return; }
  let html = '<table><thead><tr><th>Node</th><th>Type</th><th>Mastery</th><th>Uncertainty</th><th>Status</th><th>Evidence</th><th style="width:120px">Competencies</th></tr></thead><tbody>';
  learnerData.states.forEach(s => {
    const dims = [s.conceptual, s.procedural, s.implementation, s.transfer, s.fluency, s.self_confidence, s.reasoning];
    const dimLabels = ['C','P','I','T','F','S','R'];
    let compHtml = '<div class="competency-grid">';
    dims.forEach((d,i) => {
      compHtml += '<div class="competency-cell"><div class="label">'+dimLabels[i]+'</div><div class="bar"><div class="fill" style="width:'+(d*100)+'%"></div></div></div>';
    });
    compHtml += '</div>';
    html += '<tr><td>'+s.node_name+'</td><td><span class="badge badge-'+s.node_type+'">'+s.node_type+'</span></td><td>'+bar(s.mastery,'bar-mastery')+'</td><td>'+bar(s.uncertainty,'bar-uncertainty')+'</td><td><span class="badge badge-'+s.status+'">'+s.status+'</span></td><td>'+s.evidence_count+'</td><td>'+compHtml+'</td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderFrontier() {
  const el = document.getElementById('tab-frontier');
  if (!learnerData || !learnerData.frontier.length) { el.innerHTML = '<div class="empty"><p>Frontier is empty</p></div>'; return; }
  let html = '<table><thead><tr><th>#</th><th>Node</th><th>Priority</th><th>Reason</th><th>Status</th></tr></thead><tbody>';
  learnerData.frontier.forEach((f,i) => {
    html += '<tr><td>'+(i+1)+'</td><td>'+f.node_name+'</td><td>'+bar(f.priority,'bar-priority')+'</td><td>'+f.reason+'</td><td>'+f.status+'</td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderMisconceptions() {
  const el = document.getElementById('tab-misconceptions');
  if (!learnerData || !learnerData.misconceptions.length) { el.innerHTML = '<div class="empty"><p>No misconceptions detected</p></div>'; return; }
  let html = '';
  learnerData.misconceptions.forEach(m => {
    html += '<div class="node-detail">';
    html += '<h3><span class="badge badge-misconception">'+m.status+'</span> '+m.node_name+'</h3>';
    if (m.description) html += '<div class="meta" style="margin-top:4px">'+m.description+'</div>';
    html += '<div style="margin-top:6px">Confidence: '+bar(m.confidence,'bar-confidence')+'</div>';
    html += '<div class="meta" style="margin-top:4px">Detected: '+(m.first_detected_at||'—')+' · Last: '+(m.last_observed_at||'—')+'</div>';
    html += '</div>';
  });
  el.innerHTML = html;
}

function renderEvidence() {
  const el = document.getElementById('tab-evidence');
  if (!learnerData || !learnerData.evidence.length) { el.innerHTML = '<div class="empty"><p>No evidence recorded</p></div>'; return; }
  let html = '<table><thead><tr><th>Time</th><th>Node</th><th>Type</th><th>Status</th><th>Correctness</th><th>Assessor Note</th></tr></thead><tbody>';
  learnerData.evidence.forEach(e => {
    const note = (e.assessor_explanation || '').slice(0, 60) + ((e.assessor_explanation||'').length > 60 ? '...' : '');
    html += '<tr><td style="white-space:nowrap">'+(e.created_at||'').replace('T',' ').slice(0,19)+'</td><td>'+e.node_name+'</td><td>'+e.evidence_type+'</td><td><span class="badge badge-'+e.observation_status+'">'+e.observation_status+'</span></td><td>'+(e.correctness != null ? (e.correctness*100).toFixed(0)+'%' : '—')+'</td><td title="'+(e.assessor_explanation||'')+'">'+note+'</td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

async function renderSkillStates() {
  const el = document.getElementById('tab-skillstates');
  const candidate = document.getElementById('candidate-select').value;
  if (!candidate) { el.innerHTML = '<div class="empty"><p>Select a candidate to view SkillState</p></div>'; return; }
  try {
    const data = await api('/skill-states/' + encodeURIComponent(candidate));
    if (!data.skill_states || !Object.keys(data.skill_states).length) {
      el.innerHTML = '<div class="empty"><p>No SkillState data (no active session or completed assessment)</p></div>';
      return;
    }
    let html = '<div class="panel-body"><div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">Source: '+data.source+'</div>';
    html += '<table><thead><tr><th>Skill</th><th>Score (μ)</th><th>Variance</th><th>Confidence</th><th>Questions</th><th>Visualization</th></tr></thead><tbody>';
    for (const [skill, s] of Object.entries(data.skill_states)) {
      const confPct = (s.confidence * 100).toFixed(0);
      const scorePct = (s.score * 100).toFixed(0);
      const varBar = Math.min(100, (s.variance / 0.1225) * 100);
      html += '<tr><td><b>'+skill+'</b></td><td>'+scorePct+'%</td><td>'+s.variance.toFixed(4)+'</td><td>'+confPct+'%</td><td>'+s.questions_answered+'</td><td><span class="bar-wrap" style="width:120px"><span class="bar-fill bar-mastery" style="width:'+scorePct+'%"></span></span></td></tr>';
    }
    html += '</tbody></table>';
    html += '</div>';
    el.innerHTML = html;
  } catch { el.innerHTML = '<div class="error-msg">Failed to load SkillState</div>'; }
}

// --- Manage (DB wipes + question deletes) ---
const SUMMARY_LABELS = [
  ['active_sessions', 'Sessions'],
  ['learners', 'Learner rows'],
  ['knowledge_states', 'Knowledge states'],
  ['evidence', 'Evidence'],
  ['frontier', 'Frontier'],
  ['misconceptions', 'Misconceptions'],
  ['task_attempts', 'Attempts'],
  ['skill_beliefs', 'Skill beliefs'],
  ['owned_tasks', 'Owned questions'],
];

const GRAPH_SUMMARY_LABELS = [
  ['tasks_total', 'Questions'],
  ['tasks_frozen', 'Frozen graphs'],
  ['tasks_unfrozen', 'Unfrozen'],
  ['index_nodes', 'Index nodes'],
  ['index_edges', 'Index edges'],
  ['knowledge_states', 'Knowledge states'],
  ['evidence', 'Evidence'],
  ['frontier', 'Frontier'],
  ['misconceptions', 'Misconceptions'],
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
  if (!confirm('Delete ALL ' + total + ' stored rows for ' + candidate + '?\nSessions, learner model, attempts, skill beliefs and owned questions.\nThis cannot be undone.')) return;
  try {
    const r = await apiDelete('/candidate/' + encodeURIComponent(candidate));
    alert('Wiped ' + (r.deleted && r.deleted.total != null ? r.deleted.total : '?') + ' rows for ' + candidate + '.');
    await refreshAll();
  } catch (e) {
    alert('Wipe failed: ' + e.message);
  }
}

async function loadGraphSummary() {
  const el = document.getElementById('manage-graph-summary');
  if (!el) return;
  try {
    const s = await api('/graph/summary');
    let html = '<table><thead><tr><th>Table</th><th>Rows</th></tr></thead><tbody>';
    GRAPH_SUMMARY_LABELS.forEach(([key, label]) => {
      html += '<tr><td>' + label + '</td><td><b>' + (s[key] || 0) + '</b></td></tr>';
    });
    html += '<tr><td><b>Total</b></td><td><b>' + (s.total || 0) + '</b></td></tr></tbody></table>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<div class="error-msg">' + esc(e.message) + '</div>';
  }
}

async function rebuildGraph() {
  if (!confirm('Re-mirror every frozen task graph into the state index?\nNon-destructive: learner rows are untouched. Missing index rows are recreated.')) return;
  try {
    const r = await apiPost('/graph/rebuild');
    alert('Index rebuilt: mirrored ' + r.mirrored + ', skipped ' + r.skipped + '.');
    await refreshAll();
  } catch (e) {
    alert('Rebuild failed: ' + e.message);
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
    let html = '<table><thead><tr><th>Prompt</th><th>Skill</th><th>Owner</th><th>Attempts</th><th>Graph</th><th></th></tr></thead><tbody>';
    data.tasks.forEach(t => {
      const excerpt = esc((t.prompt || '').slice(0, 80)) + ((t.prompt || '').length > 80 ? '…' : '');
      const g = t.graph || {};
      const graphCell = (g.nodes && g.nodes.length)
        ? '✓ ' + g.nodes.length + 'n/' + ((g.edges || []).length) + 'e'
        : '<span style="color:var(--text-muted)">—</span>';
      html += '<tr><td title="' + esc(t.prompt || '') + '">' + excerpt + '<br><span style="color:var(--text-muted);font-size:10px">' + esc(t.id) + '</span></td>' +
        '<td>' + esc(t.skill || '') + '</td><td>' + esc(t.owner || '') + '</td><td>' + (t.attempt_count || 0) + '</td>' +
        '<td style="white-space:nowrap">' + graphCell + '</td>' +
        '<td style="white-space:nowrap"><button onclick="regenerateTask(\'' + t.id.replace(/'/g, "\\'") + '\')">Regen graph</button> ' +
        '<button class="danger" onclick="deleteTask(\'' + t.id.replace(/'/g, "\\'") + '\',' + (t.attempt_count || 0) + ')">Delete</button></td></tr>';
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

async function regenerateTask(taskId) {
  if (!confirm('Re-decompose question ' + taskId + ' and overwrite its frozen graph?\nLearner rows that reference the old index nodes keep pointing at the old nodes.')) return;
  try {
    await apiPost('/tasks/' + encodeURIComponent(taskId) + '/graph/regenerate');
    await loadManageTasks();
    await loadGraph();
    await loadGraphSummary();
  } catch (e) {
    alert('Regenerate failed: ' + e.message);
  }
}

// --- Refresh ---
async function refreshAll() {
  const candidate = document.getElementById('candidate-select').value;
  await Promise.all([loadStats(), loadGraph(), loadLearner(candidate), loadCandidateSummary(), loadManageTasks(), loadGraphSummary()]);
}

document.getElementById('candidate-select').addEventListener('change', (e) => {
  loadLearner(e.target.value);
  loadCandidateSummary();
});

document.getElementById('graph-task-select').addEventListener('change', () => {
  loadGraph();
});

// Init
(async () => {
  await loadStats();
  await loadCandidates();
  await loadGraph();
  await loadManageTasks();
  await loadGraphSummary();
})();
</script>
</body>
</html>"""


@admin_page_router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return HTMLResponse(content=_ADMIN_PAGE_HTML)
