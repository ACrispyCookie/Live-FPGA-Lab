from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

API_BASE = os.environ.get("FPGA_DEMO_API_BASE", "")


def create_web_app(*, api_base: str = API_BASE) -> FastAPI:
    app = FastAPI(title="FPGA Demo Web", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return index_html(api_base=api_base)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "web"}

    return app


def index_html(*, api_base: str = API_BASE) -> str:
    escaped = api_base.replace("\\", "\\\\").replace("'", "\\'")
    return INDEX_HTML.replace("__FPGA_DEMO_API_BASE__", escaped)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Live FPGA Lab</title>
  <style>
    :root {
      color-scheme: dark;
      --bg:#050712; --panel:#0d1326; --panel-2:#111a33; --line:#253356;
      --muted:#8ea0c6; --text:#eef4ff; --accent:#67e8f9; --accent-2:#a78bfa;
      --ok:#86efac; --warn:#facc15; --danger:#fb7185; --shadow:rgba(0,0,0,.42);
    }
    * { box-sizing: border-box; }
    body {
      margin:0; min-height:100vh; color:var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background:
        radial-gradient(circle at 12% 0%, rgba(103,232,249,.22), transparent 32rem),
        radial-gradient(circle at 88% 12%, rgba(167,139,250,.24), transparent 34rem),
        linear-gradient(180deg, #070a16 0%, var(--bg) 52%, #03040a 100%);
    }
    body::before {
      content:""; position:fixed; inset:0; pointer-events:none; opacity:.24;
      background-image: linear-gradient(rgba(103,232,249,.12) 1px, transparent 1px), linear-gradient(90deg, rgba(103,232,249,.12) 1px, transparent 1px);
      background-size:44px 44px; mask-image:linear-gradient(to bottom, black, transparent 78%);
    }
    main { width:min(1220px, calc(100vw - 28px)); margin:0 auto; padding:34px 0 64px; position:relative; }
    header { display:grid; grid-template-columns:minmax(0,1.25fr) 420px; gap:22px; align-items:stretch; margin-bottom:22px; }
    h1 { margin:0; font-size:clamp(2.6rem, 7vw, 6.8rem); letter-spacing:-.075em; line-height:.86; }
    h2 { margin:0 0 10px; letter-spacing:-.035em; } h3 { margin:0 0 8px; }
    p { color:var(--muted); line-height:1.62; }
    .hero, .panel, .demo-card, .console, .control-card {
      border:1px solid var(--line); background:linear-gradient(180deg, rgba(17,26,51,.86), rgba(8,12,25,.88));
      border-radius:28px; box-shadow:0 24px 80px var(--shadow), inset 0 1px 0 rgba(255,255,255,.04);
      backdrop-filter: blur(12px);
    }
    .hero { padding:28px; overflow:hidden; position:relative; }
    .hero::after { content:""; position:absolute; width:360px; height:360px; right:-160px; top:-130px; border-radius:50%; background:radial-gradient(circle, rgba(103,232,249,.25), transparent 64%); }
    .side { padding:22px; display:flex; flex-direction:column; justify-content:space-between; gap:18px; }
    .metrics { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .metric { border:1px solid #243458; border-radius:20px; padding:14px; background:#080d1bcc; }
    .metric .label { color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.12em; }
    .metric .value { font-size:1.55rem; font-weight:800; margin-top:6px; }
    .pill { display:inline-flex; align-items:center; gap:8px; border:1px solid #30405f; background:#0b1226cc; border-radius:999px; padding:8px 12px; font-size:.86rem; color:var(--muted); white-space:nowrap; }
    .pill.ok { color:var(--ok); border-color:rgba(134,239,172,.38); } .pill.bad { color:var(--danger); border-color:rgba(251,113,133,.45); } .pill.warn { color:var(--warn); border-color:rgba(250,204,21,.42); }
    .toolbar, .chips { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(245px, 1fr)); gap:16px; }
    .demo-card { padding:20px; min-height:250px; display:flex; flex-direction:column; justify-content:space-between; transition:.18s transform,.18s border-color,.18s box-shadow; position:relative; overflow:hidden; }
    .demo-card.available:hover { transform:translateY(-4px); border-color:rgba(103,232,249,.7); box-shadow:0 26px 92px rgba(103,232,249,.12); }
    .demo-card.placeholder { opacity:.62; }
    .demo-card::before { content:""; position:absolute; inset:0 0 auto; height:3px; background:linear-gradient(90deg,var(--accent),var(--accent-2)); opacity:.75; }
    button, select, input {
      font:inherit; border-radius:14px; border:1px solid #314264; background:#080d1b; color:var(--text); padding:11px 13px;
    }
    button { border:0; font-weight:800; color:#041018; background:linear-gradient(135deg, var(--accent), var(--ok)); cursor:pointer; box-shadow:0 10px 28px rgba(103,232,249,.18); }
    button.secondary { color:var(--text); background:#101936; border:1px solid #33466f; box-shadow:none; }
    button:disabled { cursor:not-allowed; filter:grayscale(1); opacity:.52; }
    .layout { display:grid; grid-template-columns:360px minmax(0,1fr); gap:18px; align-items:start; }
    .control-card { padding:20px; display:grid; gap:16px; }
    label { color:var(--muted); font-size:.9rem; display:grid; gap:7px; }
    input[type=range] { width:100%; accent-color:var(--accent); }
    .console { padding:18px; min-height:430px; }
    pre { margin:0; background:#030611; border:1px solid #1d2946; border-radius:18px; padding:16px; overflow:auto; color:#bed0ff; min-height:230px; max-height:52vh; }
    .timeline { display:grid; gap:10px; margin:16px 0; }
    .step { display:flex; gap:10px; align-items:center; color:var(--muted); }
    .dot { width:12px; height:12px; border-radius:50%; background:#33415f; box-shadow:0 0 0 4px rgba(255,255,255,.03); }
    .step.done .dot { background:var(--ok); } .step.active .dot { background:var(--accent); animation:pulse 1.25s infinite; } .step.failed .dot { background:var(--danger); }
    @keyframes pulse { 50% { box-shadow:0 0 0 8px rgba(103,232,249,.13); } }
    .spinner { display:inline-block; width:12px; height:12px; border:2px solid #ffffff55; border-top-color:var(--accent); border-radius:50%; animation:spin 1s linear infinite; vertical-align:-1px; }
    @keyframes spin { to { transform:rotate(360deg); } }
    #demo-page { display:none; }
    #unavailable { display:none; margin:14px 0; padding:14px 16px; border:1px solid rgba(251,113,133,.42); color:#fecdd3; background:rgba(127,29,29,.28); border-radius:18px; }
    @media (max-width:900px) { header, .layout { grid-template-columns:1fr; } .metrics { grid-template-columns:repeat(2,1fr); } }
  </style>
</head>
<body>
<main>
  <header>
    <section class="hero">
      <div class="toolbar" style="margin-bottom:18px"><span class="pill ok">real hardware</span><span class="pill">queued access</span><span class="pill">thermal protected</span></div>
      <h1>Live FPGA Lab</h1>
      <p style="max-width:680px">Launch curated portfolio demos on a real Zynq board in my homelab. Pick a project, tune safe inputs, queue a run, and watch the board state come back through the API.</p>
    </section>
    <aside class="side panel">
      <div class="toolbar"><span id="thermal-pill" class="pill">Checking FPGA...</span><span id="api-pill" class="pill">API...</span></div>
      <div class="metrics">
        <div class="metric"><div class="label">Temperature</div><div id="temp-value" class="value">--</div></div>
        <div class="metric"><div class="label">Queue</div><div id="queue-value" class="value">--</div></div>
        <div class="metric"><div class="label">Last job</div><div id="last-value" class="value">--</div></div>
        <div class="metric"><div class="label">API target</div><div id="api-value" class="value" style="font-size:.88rem; word-break:break-all">--</div></div>
      </div>
    </aside>
  </header>

  <section id="picker">
    <div class="toolbar" style="justify-content:space-between; margin:18px 0">
      <h2>Select a project</h2>
      <button class="secondary" id="refresh">Refresh status</button>
    </div>
    <div id="unavailable"></div>
    <div id="demo-grid" class="grid"></div>
  </section>

  <section id="demo-page">
    <div class="toolbar" style="justify-content:space-between; margin:18px 0">
      <button class="secondary" id="back">← Back to projects</button>
      <span id="run-state" class="pill">Idle</span>
    </div>
    <div class="layout">
      <aside class="control-card">
        <div><h2 id="active-title">GPGPU n-body simulator</h2><p id="active-copy">Programs the Zynq PL, starts the PS UART monitor, loads n-body instructions, and executes a bounded kernel run.</p></div>
        <label>Dataset
          <select id="dataset"><option value="default">default</option><option value="binary-clouds">binary clouds</option><option value="rings">rings</option></select>
        </label>
        <label>Steps per frame <span id="steps-label" class="pill">1</span>
          <input id="steps" type="range" min="1" max="16" value="1" />
        </label>
        <label>Kernel calls <span id="calls-label" class="pill">1</span>
          <input id="kernel-calls" type="range" min="1" max="4" value="1" />
        </label>
        <button id="start">Start queued FPGA run</button>
        <button class="secondary" id="status-only">Check availability</button>
      </aside>
      <section class="console">
        <h2>Run console</h2>
        <div class="timeline">
          <div class="step" data-step="submit"><span class="dot"></span><span>Submit job</span></div>
          <div class="step" data-step="queue"><span class="dot"></span><span>Respect queue / board lock</span></div>
          <div class="step" data-step="program"><span class="dot"></span><span>Program PL + start PS app</span></div>
          <div class="step" data-step="complete"><span class="dot"></span><span>Collect result artifact</span></div>
        </div>
        <pre id="output">Ready. Choose controls and start a queued hardware run.</pre>
      </section>
    </div>
  </section>
</main>
<script>
let demos = [];
let activeJob = null;
let activeDemo = null;
let pollTimer = null;
let latestThermalAvailable = false;
const API_BASE = '__FPGA_DEMO_API_BASE__';

document.getElementById('api-value').textContent = API_BASE || 'same origin /api';

async function api(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const text = await res.text();
  let data = text ? JSON.parse(text) : null;
  if (!res.ok) throw {status: res.status, data};
  return data;
}

function setStep(name, cls) {
  const el = document.querySelector(`[data-step="${name}"]`);
  if (el) el.className = `step ${cls || ''}`;
}
function resetSteps() { ['submit','queue','program','complete'].forEach(s => setStep(s, '')); }
function setOutput(value) { document.getElementById('output').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }

function setThermal(thermal) {
  latestThermalAvailable = Boolean(thermal.available);
  const pill = document.getElementById('thermal-pill');
  const unavailable = document.getElementById('unavailable');
  const temp = thermal.temperature_c == null ? 'unknown' : `${Number(thermal.temperature_c).toFixed(1)} °C`;
  document.getElementById('temp-value').textContent = temp;
  pill.textContent = thermal.available ? `FPGA available · ${temp}` : `Unavailable · ${temp}`;
  pill.className = thermal.available ? 'pill ok' : 'pill bad';
  unavailable.style.display = thermal.available ? 'none' : 'block';
  unavailable.textContent = thermal.reason || 'FPGA is currently unavailable. New runs are disabled until the thermal guard clears.';
  document.querySelectorAll('button[data-demo]').forEach(btn => { btn.disabled = !thermal.available || btn.dataset.available !== 'true'; });
  const start = document.getElementById('start');
  if (start) start.disabled = !thermal.available || !activeDemo;
}

function renderDemos() {
  const grid = document.getElementById('demo-grid');
  grid.innerHTML = '';
  demos.forEach(demo => {
    const card = document.createElement('article');
    card.className = `demo-card ${demo.available ? 'available' : 'placeholder'}`;
    card.innerHTML = `<div><div class="chips"><span class="pill ${demo.available ? 'ok' : 'warn'}">${demo.available ? 'live' : 'placeholder'}</span><span class="pill">${demo.kind}</span></div><h2>${demo.name}</h2><p>${demo.summary}</p><div class="chips"><span class="pill">${demo.board}</span></div></div>`;
    const btn = document.createElement('button');
    btn.textContent = demo.available ? 'Open control panel' : 'Coming soon';
    btn.dataset.demo = demo.id;
    btn.dataset.available = String(demo.available);
    btn.disabled = !demo.available || !latestThermalAvailable;
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
  resetSteps();
  setOutput('Ready. Choose controls and start a queued hardware run.');
  setThermal({available: latestThermalAvailable, temperature_c: Number.parseFloat(document.getElementById('temp-value').textContent), reason: null});
}

async function refreshStatus() {
  const status = await api('/api/status');
  document.getElementById('api-pill').textContent = 'API online';
  document.getElementById('api-pill').className = 'pill ok';
  setThermal(status.thermal);
  const jobs = status.jobs || [];
  const queued = jobs.filter(j => j.status === 'queued').length;
  const running = jobs.filter(j => j.status === 'running').length;
  document.getElementById('queue-value').textContent = running ? 'running' : String(queued);
  document.getElementById('last-value').textContent = jobs[0]?.status || '--';
  return status;
}

async function load() {
  demos = await api('/api/demos');
  renderDemos();
  await refreshStatus();
  renderDemos();
  setInterval(() => refreshStatus().catch(showApiError), 8000);
}
function showApiError(err) {
  document.getElementById('api-pill').textContent = 'API offline';
  document.getElementById('api-pill').className = 'pill bad';
  setOutput(err.data || err);
}

function currentPayload() {
  return {
    steps_per_frame: Number(document.getElementById('steps').value),
    kernel_calls: Number(document.getElementById('kernel-calls').value),
    dataset: document.getElementById('dataset').value
  };
}

async function startRun() {
  const state = document.getElementById('run-state');
  resetSteps(); setStep('submit', 'active');
  state.innerHTML = '<span class="spinner"></span> submitting';
  setOutput({input: currentPayload(), message: 'Submitting queued hardware job...'});
  try {
    activeJob = await api(`/api/demos/${activeDemo.id}/run`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({input:currentPayload()})});
    setStep('submit', 'done'); setStep('queue', 'active');
    state.innerHTML = '<span class="spinner"></span> queued';
    setOutput(activeJob);
    const worker = await api('/api/worker/run-next', {method:'POST'});
    if (worker.status === 'idle') setOutput({job: activeJob, worker});
    setStep('queue', 'done'); setStep('program', 'active');
    pollJob(activeJob.id);
  } catch (err) {
    state.textContent = err.status === 503 ? 'Unavailable' : 'Error';
    setStep('submit', 'failed'); setOutput(err.data || err); await refreshStatus().catch(()=>{});
  }
}

async function pollJob(id) {
  clearTimeout(pollTimer);
  try {
    const job = await api(`/api/jobs/${id}`);
    setOutput(job);
    document.getElementById('run-state').textContent = job.status;
    if (job.status === 'running') { setStep('queue','done'); setStep('program','active'); }
    if (job.status === 'succeeded') { setStep('program','done'); setStep('complete','done'); }
    if (job.status === 'failed' || job.status === 'cancelled') { setStep('program','failed'); setStep('complete','failed'); }
    if (['queued','running'].includes(job.status)) pollTimer = setTimeout(() => pollJob(id), 1500);
    await refreshStatus();
  } catch (err) { showApiError(err); }
}

document.getElementById('steps').oninput = e => document.getElementById('steps-label').textContent = e.target.value;
document.getElementById('kernel-calls').oninput = e => document.getElementById('calls-label').textContent = e.target.value;
document.getElementById('start').onclick = startRun;
document.getElementById('status-only').onclick = () => refreshStatus().then(setOutput).catch(showApiError);
document.getElementById('refresh').onclick = () => refreshStatus().then(renderDemos).catch(showApiError);
document.getElementById('back').onclick = () => { document.getElementById('demo-page').style.display='none'; document.getElementById('picker').style.display='block'; activeDemo=null; };
load().catch(showApiError);
</script>
</body>
</html>
"""
