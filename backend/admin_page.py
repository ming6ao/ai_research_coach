"""Standalone admin/debug page for inspecting the knowledge graph and learner model.

Served at /admin as a self-contained HTML page with inline SVG graph visualization,
learner model inspector, and SkillState comparison. Requires authentication.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

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
.stats-bar { display: flex; gap: 16px; padding: 8px 20px; border-bottom: 1px solid var(--border); background: var(--bg2); font-size: 11px; color: var(--text-muted); }
.stats-bar span b { color: var(--text); }
.main { display: grid; grid-template-columns: 1fr 1fr; height: calc(100vh - 85px); }
@media (max-width: 900px) { .main { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; } }
.panel { border-right: 1px solid var(--border); overflow: auto; }
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

/* SVG graph */
.graph-container { width: 100%; height: 100%; position: relative; overflow: hidden; background: var(--bg); }
.graph-container svg { width: 100%; height: 100%; }
.node-circle { cursor: grab; transition: r 0.15s; }
.node-circle:hover { r: 14; }
.node-circle.selected { stroke: var(--accent); stroke-width: 3; }
.node-label { font-size: 10px; fill: var(--text); pointer-events: none; text-anchor: middle; dominant-baseline: central; font-family: inherit; }
.edge-line { stroke: var(--border); stroke-width: 1.5; }
.edge-label { font-size: 8px; fill: var(--text-muted); text-anchor: middle; }
.edge-marker { fill: var(--border); }

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
  <!-- Left: Knowledge Graph -->
  <div class="panel">
    <div class="panel-header">
      <h2>Knowledge Graph</h2>
      <span id="graph-info" style="font-size:11px;color:var(--text-muted)"></span>
    </div>
    <div class="graph-container" id="graph-container">
      <svg id="graph-svg"></svg>
    </div>
  </div>

  <!-- Right: Learner Model -->
  <div class="panel" style="display:flex;flex-direction:column;">
    <div class="tabs" id="right-tabs">
      <div class="tab active" data-tab="states">States</div>
      <div class="tab" data-tab="frontier">Frontier</div>
      <div class="tab" data-tab="misconceptions">Misconceptions</div>
      <div class="tab" data-tab="evidence">Evidence</div>
      <div class="tab" data-tab="updates">Updates</div>
      <div class="tab" data-tab="skillstates">SkillState</div>
    </div>
    <div style="flex:1;overflow:auto;">
      <div id="tab-states" class="tab-content active"></div>
      <div id="tab-frontier" class="tab-content"></div>
      <div id="tab-misconceptions" class="tab-content"></div>
      <div id="tab-evidence" class="tab-content"></div>
      <div id="tab-updates" class="tab-content"></div>
      <div id="tab-skillstates" class="tab-content"></div>
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

// Tab switching
document.querySelectorAll('#right-tabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#right-tabs .tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

let graphData = null;
let learnerData = null;
let selectedNodeId = null;

// --- Stats ---
async function loadStats() {
  try {
    const s = await api('/stats');
    document.getElementById('stats-bar').innerHTML =
      '<span>Nodes: <b>' + s.knowledge_nodes + '</b></span>' +
      '<span>Edges: <b>' + s.knowledge_edges + '</b></span>' +
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

// --- Graph ---
const NODE_COLORS = {
  concept: '#3b82f6', skill: '#22c55e', procedure: '#a855f7',
  problem: '#f97316', strategy: '#14b8a6', misconception: '#ef4444', domain: '#6b7280'
};

let cachedPositions = new Map();

async function loadGraph() {
  try {
    graphData = await api('/graph');
    document.getElementById('graph-info').textContent =
      graphData.nodes.length + ' nodes, ' + graphData.edges.length + ' edges';
    renderGraph();
  } catch { document.getElementById('graph-info').textContent = 'Failed to load'; }
}

function renderGraph() {
  if (!graphData) return;
  const svg = document.getElementById('graph-svg');
  const container = document.getElementById('graph-container');
  const W = container.clientWidth || 600;
  const H = container.clientHeight || 400;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

  const nodes = graphData.nodes.map((n, i) => {
    const c = cachedPositions.get(n.id);
    return {
      ...n,
      x: c ? c.x : W/2 + (Math.random()-0.5)*W*0.6,
      y: c ? c.y : H/2 + (Math.random()-0.5)*H*0.6,
      vx: 0, vy: 0, idx: i
    };
  });
  const nodeMap = {};
  nodes.forEach(n => nodeMap[n.id] = n);
  const edges = graphData.edges.filter(e => nodeMap[e.source] && nodeMap[e.target]);

  // Force simulation (skip if all positions already cached)
  const needsLayout = nodes.some(n => !cachedPositions.has(n.id));
  if (needsLayout) {
    const REPULSION = 3000, ATTRACTION = 0.005, CENTER = 0.01, DAMPING = 0.85;
    for (let iter = 0; iter < 200; iter++) {
      nodes.forEach(a => { a.vx = 0; a.vy = 0; });
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i+1; j < nodes.length; j++) {
          let dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y;
          let d = Math.sqrt(dx*dx + dy*dy) || 1;
          let f = REPULSION / (d*d);
          nodes[i].vx -= dx/d*f; nodes[i].vy -= dy/d*f;
          nodes[j].vx += dx/d*f; nodes[j].vy += dy/d*f;
        }
      }
      edges.forEach(e => {
        const a = nodeMap[e.source], b = nodeMap[e.target];
        if (!a || !b) return;
        let dx = b.x - a.x, dy = b.y - a.y;
        let d = Math.sqrt(dx*dx + dy*dy) || 1;
        let f = (d - 80) * ATTRACTION;
        a.vx += dx/d*f; a.vy += dy/d*f;
        b.vx -= dx/d*f; b.vy -= dy/d*f;
      });
      nodes.forEach(n => {
        n.vx += (W/2 - n.x) * CENTER;
        n.vy += (H/2 - n.y) * CENTER;
        n.vx *= DAMPING; n.vy *= DAMPING;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(30, Math.min(W-30, n.x));
        n.y = Math.max(30, Math.min(H-30, n.y));
      });
    }
    nodes.forEach(n => cachedPositions.set(n.id, { x: n.x, y: n.y }));
  }

  // Build SVG
  let html = '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" class="edge-marker"/></marker></defs>';

  edges.forEach(e => {
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) return;
    const mx = (a.x+b.x)/2, my = (a.y+b.y)/2;
    const label = e.edge_type.replace(/_/g,' ').split(' ').map(w=>w[0]).join('');
    html += '<line x1="'+a.x+'" y1="'+a.y+'" x2="'+b.x+'" y2="'+b.y+'" class="edge-line" marker-end="url(#arrow)"/>';
    html += '<text x="'+mx+'" y="'+(my-4)+'" class="edge-label">'+label+'</text>';
  });

  nodes.forEach(n => {
    const r = 6 + (n.importance || 0.7) * 6;
    const color = NODE_COLORS[n.type] || '#6b7280';
    const sel = n.id === selectedNodeId ? ' selected' : '';
    // Mastery overlay
    let masteryR = 0;
    if (learnerData) {
      const st = learnerData.states.find(s => s.slug === n.slug);
      if (st) masteryR = r * st.mastery;
    }
    if (masteryR > 0) {
      html += '<circle cx="'+n.x+'" cy="'+n.y+'" r="'+masteryR+'" fill="'+color+'" opacity="0.3"/>';
    }
    html += '<circle cx="'+n.x+'" cy="'+n.y+'" r="'+r+'" fill="'+color+'" class="node-circle'+sel+'" data-id="'+n.id+'" opacity="0.85"/>';
    html += '<text x="'+n.x+'" y="'+(n.y + r + 12)+'" class="node-label">'+n.slug.slice(0,16)+'</text>';
  });

  svg.innerHTML = html;

  // Click handler
  svg.querySelectorAll('.node-circle').forEach(c => {
    c.addEventListener('click', () => {
      selectedNodeId = c.dataset.id;
      renderGraph();
      showNodeDetail(c.dataset.id);
    });
  });
}

function showNodeDetail(nodeId) {
  const node = graphData.nodes.find(n => n.id === nodeId);
  if (!node) return;
  const state = learnerData ? learnerData.states.find(s => s.slug === node.slug) : null;
  const outgoing = graphData.edges.filter(e => e.source === nodeId);
  const incoming = graphData.edges.filter(e => e.target === nodeId);
  const color = NODE_COLORS[node.type] || '#6b7280';

  let html = '<div class="node-detail">';
  html += '<h3><span class="badge badge-'+node.type+'" style="background:'+color+'20;color:'+color+'">'+node.type+'</span> '+node.name+'</h3>';
  html += '<div class="meta">slug: '+node.slug+'</div>';
  if (node.description) html += '<div class="meta" style="margin-top:4px">'+node.description+'</div>';
  html += '<div class="meta" style="margin-top:4px">importance: '+(node.importance||0.7).toFixed(2)+' · status: '+node.status+'</div>';
  if (state) {
    html += '<div style="margin-top:8px;font-size:11px">';
    html += '<b>Mastery:</b> <span class="bar-wrap"><span class="bar-fill bar-mastery" style="width:'+(state.mastery*100)+'%"></span></span> '+(state.mastery*100).toFixed(1)+'%<br>';
    html += '<b>Uncertainty:</b> <span class="bar-wrap"><span class="bar-fill bar-uncertainty" style="width:'+(state.uncertainty*100)+'%"></span></span> '+(state.uncertainty*100).toFixed(1)+'%<br>';
    html += '<b>Status:</b> <span class="badge badge-'+state.status+'">'+state.status+'</span> · evidence: '+state.evidence_count;
    html += '</div>';
  }
  if (outgoing.length) {
    html += '<div class="connections"><b>Outgoing:</b><ul>';
    outgoing.forEach(e => {
      const target = graphData.nodes.find(n => n.id === e.target);
      html += '<li>'+e.edge_type+' → '+(target ? target.slug : e.target.slice(0,8))+'</li>';
    });
    html += '</ul></div>';
  }
  if (incoming.length) {
    html += '<div class="connections"><b>Incoming:</b><ul>';
    incoming.forEach(e => {
      const source = graphData.nodes.find(n => n.id === e.source);
      html += '<li>'+e.edge_type+' ← '+(source ? source.slug : e.source.slice(0,8))+'</li>';
    });
    html += '</ul></div>';
  }
  html += '</div>';

  const tabContent = document.getElementById('tab-states');
  const existing = tabContent.querySelector('.node-detail');
  if (existing) existing.remove();
  tabContent.insertAdjacentHTML('afterbegin', html);
}

// --- Learner data ---
async function loadLearner(candidate) {
  if (!candidate) { learnerData = null; renderTabs(); return; }
  try { learnerData = await api('/learner/' + encodeURIComponent(candidate)); } catch { learnerData = null; }
  renderTabs();
  renderGraph();
}

function renderTabs() {
  renderStates(); renderFrontier(); renderMisconceptions(); renderEvidence(); renderUpdates(); renderSkillStates();
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
    html += '<tr><td>'+s.slug+'</td><td><span class="badge badge-'+s.node_type+'">'+s.node_type+'</span></td><td>'+bar(s.mastery,'bar-mastery')+'</td><td>'+bar(s.uncertainty,'bar-uncertainty')+'</td><td><span class="badge badge-'+s.status+'">'+s.status+'</span></td><td>'+s.evidence_count+'</td><td>'+compHtml+'</td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderFrontier() {
  const el = document.getElementById('tab-frontier');
  if (!learnerData || !learnerData.frontier.length) { el.innerHTML = '<div class="empty"><p>Frontier is empty</p></div>'; return; }
  let html = '<table><thead><tr><th>#</th><th>Node</th><th>Priority</th><th>Reason</th><th>Status</th></tr></thead><tbody>';
  learnerData.frontier.forEach((f,i) => {
    html += '<tr><td>'+(i+1)+'</td><td>'+f.slug+'</td><td>'+bar(f.priority,'bar-priority')+'</td><td>'+f.reason+'</td><td>'+f.status+'</td></tr>';
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
    html += '<h3><span class="badge badge-misconception">'+m.status+'</span> '+m.slug+'</h3>';
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
    html += '<tr><td style="white-space:nowrap">'+(e.created_at||'').replace('T',' ').slice(0,19)+'</td><td>'+e.slug+'</td><td>'+e.evidence_type+'</td><td><span class="badge badge-'+e.observation_status+'">'+e.observation_status+'</span></td><td>'+(e.correctness != null ? (e.correctness*100).toFixed(0)+'%' : '—')+'</td><td title="'+(e.assessor_explanation||'')+'">'+note+'</td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderUpdates() {
  const el = document.getElementById('tab-updates');
  if (!learnerData || !learnerData.updates.length) { el.innerHTML = '<div class="empty"><p>No state updates yet</p></div>'; return; }
  let html = '<table><thead><tr><th>Time</th><th>Node</th><th>Mastery</th><th>Uncertainty</th><th>Reason</th></tr></thead><tbody>';
  learnerData.updates.forEach(u => {
    html += '<tr><td style="white-space:nowrap">'+(u.created_at||'').replace('T',' ').slice(0,19)+'</td><td>'+u.slug+'</td><td>'+(u.previous_mastery*100).toFixed(0)+'% → '+(u.new_mastery*100).toFixed(0)+'%</td><td>'+(u.previous_uncertainty*100).toFixed(0)+'% → '+(u.new_uncertainty*100).toFixed(0)+'%</td><td>'+u.update_reason+'</td></tr>';
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

    // Comparison with MVP aggregate mastery
    if (learnerData && learnerData.states.length) {
      html += '<div style="margin-top:16px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">MVP Aggregate Mastery by Skill</div>';
      html += '<table style="margin-top:8px"><thead><tr><th>Skill</th><th>Avg Mastery</th><th>Avg Uncertainty</th><th>Nodes</th></tr></thead><tbody>';
      const bySkill = {};
      learnerData.states.forEach(s => {
        const sk = s.node_type === 'skill' ? s.node_name : (s.node_type);
        if (!bySkill[sk]) bySkill[sk] = { mastery: 0, uncertainty: 0, count: 0 };
        bySkill[sk].mastery += s.mastery;
        bySkill[sk].uncertainty += s.uncertainty;
        bySkill[sk].count++;
      });
      for (const [sk, v] of Object.entries(bySkill)) {
        const avg = v.mastery / v.count;
        const avgU = v.uncertainty / v.count;
        html += '<tr><td>'+sk+'</td><td>'+bar(avg,'bar-mastery')+'</td><td>'+bar(avgU,'bar-uncertainty')+'</td><td>'+v.count+'</td></tr>';
      }
      html += '</tbody></table>';
    }
    html += '</div>';
    el.innerHTML = html;
  } catch { el.innerHTML = '<div class="error-msg">Failed to load SkillState</div>'; }
}

// --- Refresh ---
async function refreshAll() {
  const candidate = document.getElementById('candidate-select').value;
  await Promise.all([loadStats(), loadGraph(), loadLearner(candidate)]);
}

document.getElementById('candidate-select').addEventListener('change', (e) => {
  loadLearner(e.target.value);
});

// Init
(async () => {
  await loadStats();
  await loadCandidates();
  await loadGraph();
})();
</script>
</body>
</html>"""


@admin_page_router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return HTMLResponse(content=_ADMIN_PAGE_HTML)
