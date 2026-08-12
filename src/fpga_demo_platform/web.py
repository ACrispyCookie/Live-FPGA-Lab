from __future__ import annotations

import os

API_BASE = os.environ.get("FPGA_DEMO_API_BASE", "")


def index_html(*, api_base: str = API_BASE) -> str:
    escaped = api_base.replace("\\", "\\\\").replace("'", "\\'")
    return INDEX_HTML.replace("__FPGA_DEMO_API_BASE__", escaped)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Live FPGA Demo</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1020; --card:#121a33; --muted:#91a0bf; --text:#e8eeff; --accent:#6ee7ff; --danger:#ff6b6b; --ok:#7cf29a; --warn:#ffd166; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: radial-gradient(circle at top left, #1a2a5a 0, var(--bg) 42rem); color:var(--text); }
    main { width:min(1120px, calc(100vw - 32px)); margin:0 auto; padding:44px 0 64px; }
    header { display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:28px; }
    h1 { margin:0; font-size:clamp(2.2rem, 5vw, 4.8rem); letter-spacing:-0.06em; line-height:.9; }
    h2 { margin:0 0 12px; }
    p { color:var(--muted); line-height:1.6; }
    .pill { border:1px solid #30405f; background:#0f1830cc; border-radius:999px; padding:8px 12px; font-size:.9rem; color:var(--muted); white-space:nowrap; }
    .pill.ok { color:var(--ok); border-color:#24583a; }
    .pill.bad { color:var(--danger); border-color:#6b2525; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:16px; }
    .card { background:linear-gradient(180deg, #15203dcc, var(--card)); border:1px solid #26375c; border-radius:22px; padding:20px; box-shadow:0 20px 80px #0007; }
    .demo { min-height:220px; display:flex; flex-direction:column; justify-content:space-between; transition:.18s transform,.18s border-color; }
    .demo.available:hover { transform:translateY(-3px); border-color:#4ca4d6; }
    .demo.placeholder { opacity:.58; }
    .meta { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
    button { border:0; border-radius:14px; padding:12px 16px; font-weight:700; color:#06121c; background:linear-gradient(135deg, var(--accent), #7cf29a); cursor:pointer; }
    button:disabled { cursor:not-allowed; filter:grayscale(1); opacity:.55; }
    .danger { color:var(--danger); }
    .ok-text { color:var(--ok); }
    .warn-text { color:var(--warn); }
    #demo-page { display:none; }
    .toolbar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:18px 0; }
    pre { background:#070b16; border:1px solid #1f2e4c; border-radius:16px; padding:16px; overflow:auto; color:#b9c7e8; min-height:120px; }
    .spinner { display:inline-block; width:12px; height:12px; border:2px solid #ffffff55; border-top-color:var(--accent); border-radius:50%; animation:spin 1s linear infinite; vertical-align:-1px; }
    @keyframes spin { to { transform:rotate(360deg); } }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Live FPGA Lab</h1>
      <p>Pick a project, queue a safe run, and watch a real board in the homelab execute the selected demo.</p>
    </div>
    <div id="thermal-pill" class="pill">Checking FPGA...</div>
  </header>

  <section id="picker">
    <h2>Select a project</h2>
    <div id="unavailable" class="card danger" style="display:none"></div>
    <div id="demo-grid" class="grid"></div>
  </section>

  <section id="demo-page">
    <button id="back">← Back to projects</button>
    <div class="card" style="margin-top:18px">
      <h2 id="active-title">GPGPU n-body simulator</h2>
      <p id="active-copy">This run programs the Zynq PL, starts the PS UART monitor, loads n-body instructions, and executes one kernel call.</p>
      <div class="toolbar">
        <label>Steps per frame <input id="steps" type="number" min="1" max="10240" value="1" /></label>
        <button id="start">Start queued FPGA run</button>
        <span id="run-state" class="pill">Idle</span>
      </div>
      <pre id="output">No run yet.</pre>
    </div>
  </section>
</main>
<script>
const placeholderDemos = [];
let demos = [];
let activeJob = null;
let activeDemo = null;
let pollTimer = null;
const API_BASE = '__FPGA_DEMO_API_BASE__';

async function api(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const text = await res.text();
  let data = text ? JSON.parse(text) : null;
  if (!res.ok) throw {status: res.status, data};
  return data;
}

function setThermal(thermal) {
  const pill = document.getElementById('thermal-pill');
  const unavailable = document.getElementById('unavailable');
  const temp = thermal.temperature_c == null ? 'unknown' : `${thermal.temperature_c.toFixed(1)} °C`;
  pill.textContent = thermal.available ? `FPGA available · ${temp}` : `Unavailable · ${temp}`;
  pill.className = thermal.available ? 'pill ok' : 'pill bad';
  unavailable.style.display = thermal.available ? 'none' : 'block';
  unavailable.textContent = thermal.reason || 'FPGA is currently unavailable; runs are disabled until it cools down.';
  document.querySelectorAll('button[data-demo]').forEach(btn => { btn.disabled = !thermal.available || btn.dataset.available !== 'true'; });
  document.getElementById('start').disabled = !thermal.available;
}

function renderDemos() {
  const grid = document.getElementById('demo-grid');
  grid.innerHTML = '';
  [...demos, ...placeholderDemos].forEach(demo => {
    const card = document.createElement('article');
    card.className = `card demo ${demo.available ? 'available' : 'placeholder'}`;
    card.innerHTML = `<div><h2>${demo.name}</h2><p>${demo.summary}</p><div class="meta"><span class="pill">${demo.kind}</span><span class="pill">${demo.board}</span>${demo.placeholder ? '<span class="pill">placeholder</span>' : '<span class="pill ok">live</span>'}</div></div>`;
    const btn = document.createElement('button');
    btn.textContent = demo.available ? 'Open demo' : 'Coming soon';
    btn.dataset.demo = demo.id;
    btn.dataset.available = String(demo.available);
    btn.disabled = !demo.available;
    btn.onclick = () => openDemo(demo);
    card.appendChild(btn);
    grid.appendChild(card);
  });
}

function openDemo(demo) {
  if (!demo.available) return;
  activeDemo = demo;
  document.getElementById('picker').style.display = 'none';
  document.getElementById('demo-page').style.display = 'block';
  document.getElementById('active-title').textContent = demo.name;
  document.getElementById('run-state').textContent = 'Idle';
  document.getElementById('output').textContent = 'Ready to queue a run.';
}

async function refreshStatus() {
  const status = await api('/api/status');
  setThermal(status.thermal);
  return status;
}

async function load() {
  demos = await api('/api/demos');
  renderDemos();
  await refreshStatus();
  setInterval(refreshStatus, 10000);
}

async function startRun() {
  const output = document.getElementById('output');
  const state = document.getElementById('run-state');
  output.textContent = 'Submitting job...';
  state.innerHTML = '<span class="spinner"></span> queued';
  try {
    activeJob = await api(`/api/demos/${activeDemo.id}/run`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({input:{steps_per_frame:Number(document.getElementById('steps').value)}})});
    output.textContent = JSON.stringify(activeJob, null, 2);
    await api('/api/worker/run-next', {method:'POST'});
    pollJob(activeJob.id);
  } catch (err) {
    state.textContent = err.status === 503 ? 'Unavailable' : 'Error';
    output.textContent = JSON.stringify(err.data || err, null, 2);
    await refreshStatus();
  }
}

async function pollJob(id) {
  clearTimeout(pollTimer);
  const job = await api(`/api/jobs/${id}`);
  document.getElementById('output').textContent = JSON.stringify(job, null, 2);
  document.getElementById('run-state').textContent = job.status;
  if (['queued','running'].includes(job.status)) pollTimer = setTimeout(() => pollJob(id), 1500);
}

document.getElementById('start').onclick = startRun;
document.getElementById('back').onclick = () => { document.getElementById('demo-page').style.display='none'; document.getElementById('picker').style.display='block'; };
load().catch(err => { document.getElementById('demo-grid').textContent = JSON.stringify(err, null, 2); });
</script>
</body>
</html>
"""
