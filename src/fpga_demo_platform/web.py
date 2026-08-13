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
    :root{color-scheme:dark;--bg:#070a12;--panel:#0d1324;--panel2:#111a31;--line:#26344f;--text:#edf4ff;--muted:#93a4c4;--accent:#67e8f9;--ok:#86efac;--warn:#fde68a;--bad:#fb7185}
    *{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at 20% 0%,#12345c 0,transparent 34rem),linear-gradient(180deg,#070a12,#03050b);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif} 
    main{width:min(1180px,calc(100vw - 32px));margin:auto;padding:32px 0 56px}.hero{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:18px;margin-bottom:18px}.card{background:linear-gradient(180deg,rgba(17,26,49,.92),rgba(8,12,24,.94));border:1px solid var(--line);border-radius:22px;box-shadow:0 20px 80px rgba(0,0,0,.35)}.intro{padding:26px}.status{padding:18px;display:grid;gap:12px}h1{font-size:clamp(2.4rem,7vw,5.8rem);letter-spacing:-.07em;line-height:.9;margin:0}h2,h3{letter-spacing:-.03em;margin:0 0 10px}p{color:var(--muted);line-height:1.55}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.badge{display:inline-flex;align-items:center;max-width:100%;border:1px solid #34435f;border-radius:999px;padding:6px 10px;color:var(--muted);font-size:.85rem;white-space:nowrap}.badge.ok{color:var(--ok);border-color:#2d6943}.badge.bad{color:var(--bad);border-color:#713042}.badge.warn{color:var(--warn);border-color:#765e24}.metric{display:flex;justify-content:space-between;gap:10px;border:1px solid #22304b;border-radius:14px;padding:10px 12px;background:#080d1b}.metric span:first-child{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.project{padding:18px;min-height:210px;display:flex;flex-direction:column;justify-content:space-between}.project.placeholder{opacity:.62}.project.live{border-color:#3b82a0}.project .meta{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}button,select,input{font:inherit;border-radius:12px;border:1px solid #31425f;background:#0a1020;color:var(--text);padding:10px 12px}button{border:0;background:linear-gradient(135deg,var(--accent),var(--ok));color:#041018;font-weight:800;cursor:pointer}button.secondary{background:#111b33;color:var(--text);border:1px solid #31425f}button:disabled{opacity:.5;filter:grayscale(1);cursor:not-allowed}.demo{display:none;grid-template-columns:360px minmax(0,1fr);gap:16px;margin-top:18px}.controls{padding:18px;display:grid;gap:14px}.viewer{min-height:610px;display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}.viewer-head{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:center}.canvas-wrap{position:relative;min-height:430px;background:radial-gradient(circle at 50% 45%,#102244,#02040a 66%)}canvas{width:100%;height:100%;display:block}.overlay{position:absolute;left:16px;bottom:16px;right:16px;border:1px solid #2c3b5a;background:rgba(5,9,18,.82);border-radius:14px;padding:12px;color:var(--muted)}.console{border-top:1px solid var(--line);padding:12px 18px}pre{margin:0;max-height:170px;overflow:auto;background:#030711;border:1px solid #1d2942;border-radius:12px;padding:12px;color:#c4d3ff}.timeline{display:grid;gap:8px}.step{display:flex;align-items:center;gap:8px;color:var(--muted)}.dot{width:10px;height:10px;border-radius:50%;background:#34415a}.step.active .dot{background:var(--accent);box-shadow:0 0 0 6px rgba(103,232,249,.12)}.step.done .dot{background:var(--ok)}.step.fail .dot{background:var(--bad)}label{display:grid;gap:7px;color:var(--muted)}input[type=range]{width:100%;accent-color:var(--accent)}@media(max-width:900px){.hero,.demo{grid-template-columns:1fr}.viewer{min-height:520px}.canvas-wrap{min-height:360px}}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <div class="intro card"><div class="row"><span class="badge ok">real FPGA</span><span class="badge">queued runs</span><span class="badge">thermal guard</span></div><h1>Live FPGA Lab</h1><p>Choose a project, reserve the board through the queue, and view the demo output in a project-specific interface.</p></div>
    <aside class="status card"><h2>Board status</h2><div class="metric"><span>API</span><b id="api-state">checking</b></div><div class="metric"><span>Thermal</span><b id="thermal-state">--</b></div><div class="metric"><span>Queue</span><b id="queue-state">--</b></div><button class="secondary" id="refresh">Refresh</button></aside>
  </section>
  <section id="picker"><h2 style="margin:0 0 14px">Projects</h2><div id="unavailable" class="badge bad" style="display:none;margin-bottom:14px"></div><div id="demo-grid" class="grid"></div></section>
  <section id="demo" class="demo">
    <aside class="controls card"><button class="secondary" id="back">← Projects</button><div><h2 id="demo-title">GPGPU n-body</h2><p id="demo-summary">Run and visualize the n-body project.</p></div><label>Dataset<select id="dataset"><option value="default">default</option><option value="binary-clouds">binary clouds</option><option value="rings">rings</option></select></label><label>Steps per kernel call <b id="steps-label">1</b><input id="steps" type="range" min="1" max="16" value="1"></label><label>Kernel calls <b id="calls-label">1</b><input id="calls" type="range" min="1" max="4" value="1"></label><button id="start">Run on FPGA</button><div class="timeline"><div class="step" data-step="submit"><span class="dot"></span>Submit</div><div class="step" data-step="queue"><span class="dot"></span>Queue lock</div><div class="step" data-step="run"><span class="dot"></span>Program + execute</div><div class="step" data-step="display"><span class="dot"></span>Display frames</div></div></aside>
    <section class="viewer card"><div class="viewer-head"><h2>n-body output</h2><span id="job-state" class="badge">idle</span></div><div class="canvas-wrap"><canvas id="nbody"></canvas><div class="overlay" id="viewer-note">Run the demo to load FPGA output frames. Drag inside the viewer to rotate; scroll to zoom.</div></div><div class="console"><pre id="output">No run yet.</pre></div></section>
  </section>
</main>
<script>
const API_BASE='__FPGA_DEMO_API_BASE__';let demos=[],activeDemo=null,thermalOk=false,eventSource=null;let frames=[],frameIndex=0,angleX=.55,angleY=.65,zoom=1,drag=null;
const $=id=>document.getElementById(id);function api(path,opt){return fetch(`${API_BASE}${path}`,opt).then(async r=>{const t=await r.text();const d=t?JSON.parse(t):null;if(!r.ok)throw{status:r.status,data:d};return d})}function out(x){$('output').textContent=typeof x==='string'?x:JSON.stringify(x,null,2)}function step(name,cls=''){document.querySelector(`[data-step="${name}"]`).className=`step ${cls}`}function resetSteps(){['submit','queue','run','display'].forEach(s=>step(s))}
async function refresh(){try{const s=await api('/api/status');$('api-state').textContent='online';thermalOk=!!s.thermal.available;const temp=s.thermal.temperature_c==null?'unknown':`${Number(s.thermal.temperature_c).toFixed(1)} °C`;$('thermal-state').textContent=thermalOk?temp:`blocked (${temp})`;$('thermal-state').style.color=thermalOk?'var(--ok)':'var(--bad)';const q=(s.jobs||[]).filter(j=>j.status==='queued').length;const running=(s.jobs||[]).some(j=>j.status==='running');$('queue-state').textContent=running?'running':String(q);$('unavailable').style.display=thermalOk?'none':'inline-flex';$('unavailable').textContent=s.thermal.reason||'FPGA unavailable';renderDemos()}catch(e){$('api-state').textContent='offline';$('api-state').style.color='var(--bad)';out(e.data||e)}}
function renderDemos(){const g=$('demo-grid');g.innerHTML='';demos.forEach(d=>{const c=document.createElement('article');c.className=`project card ${d.available?'live':'placeholder'}`;c.innerHTML=`<div><div class="row"><span class="badge ${d.available?'ok':'warn'}">${d.available?'live':'coming soon'}</span></div><h2>${d.name}</h2><p>${d.summary}</p></div>`;const b=document.createElement('button');b.textContent=d.available?'Open demo':'Placeholder';b.disabled=!d.available||!thermalOk;b.onclick=()=>openDemo(d);c.appendChild(b);g.appendChild(c)})}
async function load(){demos=await api('/api/demos');renderDemos();await refresh()}function openDemo(d){activeDemo=d;$('picker').style.display='none';$('demo').style.display='grid';$('demo-title').textContent=d.name;$('demo-summary').textContent=d.summary;resetSteps();drawPlaceholder()}function currentPayload(){return{dataset:$('dataset').value,steps_per_frame:Number($('steps').value),kernel_calls:Number($('calls').value)}}
async function startRun(){if(!activeDemo)return;resetSteps();step('submit','active');$('job-state').textContent='submitting';out({input:currentPayload()});try{const job=await api(`/api/demos/${activeDemo.id}/run`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({input:currentPayload()})});step('submit','done');step('queue','active');watchJob(job.id);fetch(`${API_BASE}/api/worker/run-next`,{method:'POST'}).catch(e=>out({worker_error:String(e)}))}catch(e){step('submit','fail');$('job-state').textContent=e.status===503?'unavailable':'error';out(e.data||e);await refresh()}}
function watchJob(id){if(eventSource)eventSource.close();eventSource=new EventSource(`${API_BASE}/api/jobs/${id}/events`);eventSource.addEventListener('job',ev=>{const job=JSON.parse(ev.data);$('job-state').textContent=job.status;out(job);if(job.status==='running'){step('queue','done');step('run','active')}if(!['queued','running'].includes(job.status)){eventSource.close();if(job.status==='succeeded'){step('run','done');step('display','active');loadFrames(job)}else{step('run','fail');}}});eventSource.onerror=()=>{$('job-state').textContent='event stream reconnecting'}}
function loadFrames(job){const result=job.result||{};frames=result.frames||[];if(frames.length){frameIndex=0;step('display','done');$('viewer-note').textContent=`Loaded ${frames.length} FPGA frame(s) from artifact ${job.id}.`;draw()}else{$('viewer-note').textContent='Run completed, but no n-body frame artifact was returned.';step('display','fail')}}
const canvas=$('nbody'),ctx=canvas.getContext('2d');function resize(){const r=canvas.parentElement.getBoundingClientRect();canvas.width=Math.max(1,r.width*devicePixelRatio);canvas.height=Math.max(1,r.height*devicePixelRatio);draw()}addEventListener('resize',resize);function project(p){const [x,y,z]=p;let cy=Math.cos(angleY),sy=Math.sin(angleY),cx=Math.cos(angleX),sx=Math.sin(angleX);let x1=x*cy-z*sy,z1=x*sy+z*cy,y1=y*cx-z1*sx,z2=y*sx+z1*cx+900/zoom;const s=520*zoom/Math.max(120,z2);return[canvas.width/2+x1*s,canvas.height/2-y1*s,s]}function drawPlaceholder(){frames=[{step:0,positions:Array.from({length:32},(_,i)=>[i*12-190,((i*29)&255)-128,((i*47)&255)-128])}];frameIndex=0;draw()}function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#030711';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.strokeStyle='rgba(103,232,249,.14)';for(let i=0;i<14;i++){ctx.beginPath();ctx.moveTo(0,i*canvas.height/14);ctx.lineTo(canvas.width,i*canvas.height/14);ctx.stroke()}const f=frames[frameIndex]||frames[0];if(!f)return;const pts=f.positions.map((p,i)=>({i,p,pr:project(p)})).sort((a,b)=>a.pr[2]-b.pr[2]);for(const o of pts){const [x,y,s]=o.pr;ctx.beginPath();ctx.fillStyle=`hsl(${(o.i*47)%360} 90% 65%)`;ctx.shadowBlur=18;ctx.shadowColor=ctx.fillStyle;ctx.arc(x,y,Math.max(4,9*s),0,Math.PI*2);ctx.fill()}ctx.shadowBlur=0;ctx.fillStyle='#dbeafe';ctx.font=`${14*devicePixelRatio}px ui-monospace,monospace`;ctx.fillText(`step ${f.step??0} · frame ${frameIndex+1}/${frames.length}`,18*devicePixelRatio,28*devicePixelRatio)}canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,angleX,angleY];canvas.setPointerCapture(e.pointerId)});canvas.addEventListener('pointermove',e=>{if(!drag)return;angleY=drag[3]+(e.clientX-drag[0])*.008;angleX=Math.max(-1.4,Math.min(1.4,drag[2]+(e.clientY-drag[1])*.008));draw()});canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.35,Math.min(3,zoom*(e.deltaY<0?1.1:.9)));draw()},{passive:false});setInterval(()=>{if(frames.length>1){frameIndex=(frameIndex+1)%frames.length;draw()}},900);
$('steps').oninput=e=>$('steps-label').textContent=e.target.value;$('calls').oninput=e=>$('calls-label').textContent=e.target.value;$('start').onclick=startRun;$('back').onclick=()=>{$('demo').style.display='none';$('picker').style.display='block'};$('refresh').onclick=refresh;resize();load().catch(e=>out(e.data||e));
</script>
</body>
</html>
"""
