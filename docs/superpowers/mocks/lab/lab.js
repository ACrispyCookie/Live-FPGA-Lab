// Styled mock of the Live FPGA Lab (throwaway). Renders one of several example states and the copper trace.
(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const state = new URLSearchParams(location.search).get('state') || 'idle';
  document.querySelectorAll('.mockbar a').forEach(a => a.classList.toggle('on', a.getAttribute('href') === `?state=${state}`));

  /* ---------- example data (the real app reads the socket) ---------- */
  const DEMOS = [
    ['gpgpu-nbody', 'GPGPU n-body simulator', 'Interactive n-body simulation running on the GPGPU, drawn in 3D in your browser.', 'Interactive 3D view'],
    ['dvd-logo-video', 'DVD Logo HDMI', 'The bouncing DVD logo, drawn by the FPGA and captured from its HDMI output.', 'Live HDMI capture'],
    ['gpgpu-ripple', 'GPGPU ripple animation', 'The GPGPU renders an animated ripple frame after frame.', 'Live HDMI capture'],
    ['gpgpu-triangle', 'GPGPU triangle', 'The GPGPU rasterizes one triangle into the framebuffer.', 'Live HDMI capture'],
    ['gpgpu-metaballs', 'GPGPU metaballs', 'Glowing blobs drift across the screen, merging and splitting.', 'Live HDMI capture'],
    ['gpgpu-julia', 'GPGPU Julia set', 'An animated Julia set morphs frame after frame.', 'Live HDMI capture'],
    ['gpgpu-cube', 'GPGPU spinning cube', 'A flat-shaded cube spinning in perspective.', 'Live HDMI capture'],
    ['gpgpu-mandelbrot', 'GPGPU Mandelbrot zoom', 'An endless zoom into the Mandelbrot set.', 'Live HDMI capture'],
  ];
  const name = id => (DEMOS.find(d => d[0] === id) || [])[1] || id;

  // thumbnails: drawn in the palette; the real build serves a capture frame per demo when one exists
  const T = {
    'gpgpu-nbody': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><g fill="#d8b46a">${Array.from({length:70},(_,i)=>{const a=i*2.4,r=6+i*0.42;return `<circle cx="${(60+Math.cos(a)*r).toFixed(1)}" cy="${(38+Math.sin(a)*r*0.55).toFixed(1)}" r="${i%7?1:1.6}"/>`}).join('')}</g><circle cx="60" cy="38" r="3" fill="#41e2f2"/></svg>`,
    'dvd-logo-video': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><path d="M12 64 L48 18 L84 50 L108 24" fill="none" stroke="#3b7a82" stroke-width="2" stroke-dasharray="4 5" stroke-linecap="round"/><rect x="70" y="40" width="30" height="14" rx="7" fill="#41e2f2"/><text x="85" y="50.5" font-family="Bricolage Grotesque,sans-serif" font-weight="800" font-size="9" fill="#05252a" text-anchor="middle">DVD</text></svg>`,
    'gpgpu-ripple': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><g fill="none" stroke-width="2"><circle cx="60" cy="38" r="8" stroke="#41e2f2"/><circle cx="60" cy="38" r="18" stroke="#3b7a82"/><circle cx="60" cy="38" r="28" stroke="#41e2f2" opacity=".7"/><circle cx="60" cy="38" r="38" stroke="#3b7a82" opacity=".6"/></g></svg>`,
    'gpgpu-triangle': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><path d="M60 12 L100 62 L20 62 Z" fill="#41e2f2"/><path d="M60 12 L100 62 L60 62 Z" fill="#3b7a82"/></svg>`,
    'gpgpu-metaballs': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><g fill="#41e2f2" opacity=".85"><circle cx="42" cy="36" r="16"/><circle cx="64" cy="44" r="13"/><circle cx="84" cy="30" r="10"/></g><circle cx="56" cy="40" r="7" fill="#d8b46a"/></svg>`,
    'gpgpu-julia': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><g fill="none" stroke-width="2.5" stroke-linecap="round"><path d="M30 50 C40 20 70 20 70 40 S50 60 60 30" stroke="#41e2f2"/><path d="M90 26 C80 56 50 56 50 36 S70 16 60 46" stroke="#3b7a82"/></g><circle cx="60" cy="38" r="2.5" fill="#d8b46a"/></svg>`,
    'gpgpu-cube': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><path d="M44 28 L76 20 L84 44 L52 52 Z" fill="#41e2f2"/><path d="M52 52 L84 44 L80 62 L48 68 Z" fill="#2c6f78"/><path d="M44 28 L52 52 L48 68 L38 46 Z" fill="#3b7a82"/></svg>`,
    'gpgpu-mandelbrot': `<svg viewBox="0 0 120 76"><rect width="120" height="76" fill="#183539"/><path d="M78 38 C78 24 66 16 54 20 C46 23 44 34 50 38 C44 42 46 53 54 56 C66 60 78 52 78 38 Z" fill="#3b7a82"/><circle cx="40" cy="38" r="9" fill="#3b7a82"/><circle cx="28" cy="38" r="3.5" fill="#41e2f2"/><path d="M78 38 C78 24 66 16 54 20 C46 23 44 34 50 38 C44 42 46 53 54 56 C66 60 78 52 78 38 Z" fill="none" stroke="#41e2f2" stroke-width="1.5"/></svg>`,
  };

  const RECENT = [
    ['gpgpu-nbody', 'Ended by the visitor', '14:02', 'ok'],
    ['gpgpu-metaballs', 'Time ran out while others were waiting', '13:41', ''],
    ['dvd-logo-video', 'Ended by the visitor', '13:30', 'ok'],
    ['gpgpu-cube', 'Programming failed', '12:08', 'bad'],
  ];

  /* ---------- per-state model ---------- */
  const S = {
    connecting: { online: null, pill: 'Connecting', status: 'Connecting', temp: null, queue: null, running: null },
    idle:       { online: true, pill: 'Idle', status: 'Idle', temp: 61.9, queue: 0, running: null },
    busy:       { online: true, pill: 'Running', status: 'Running', temp: 63.0, queue: 1, running: 'gpgpu-cube' },
    arrival:    { online: true, pill: 'Programming', status: 'Programming', temp: 61.9, queue: 0, running: 'gpgpu-nbody', mine: 'gpgpu-nbody', from: 'njason.dev' },
    queued:     { online: true, pill: 'Running', status: 'Running', temp: 63.4, queue: 3, running: 'gpgpu-metaballs', mine: 'gpgpu-nbody', place: 2, eta: 270 },
    starting:   { online: true, pill: 'Programming', status: 'Programming', temp: 62.0, queue: 0, running: 'gpgpu-julia', mine: 'gpgpu-julia' },
    active:     { online: true, pill: 'Running', status: 'Running', temp: 64.1, queue: 1, running: 'gpgpu-nbody', mine: 'gpgpu-nbody', left: 252 },
    ending:     { online: true, pill: 'Resetting', status: 'Resetting', temp: 63.2, queue: 1, running: null, mine: 'gpgpu-nbody' },
    project:    { online: true, pill: 'In use for GPGPU testing', status: 'GPGPU testing', temp: 61.8, queue: 0, running: null, project: true },
    fault:      { online: false, pill: 'Fault', status: 'Fault', temp: 71.3, queue: 0, running: null, fault: 'Over temperature' },
    offline:    { online: false, pill: 'Offline', status: 'Offline', temp: null, queue: 0, running: null },
  };
  const m = S[state] || S.idle;
  const isActive = state === 'active';

  const dur = s => { const mm = Math.floor(s / 60), ss = s % 60; return mm ? `${mm}m ${String(ss).padStart(2, '0')}s` : `${ss}s`; };

  /* ---------- top bar pill ---------- */
  const pill = document.getElementById('pill');
  document.getElementById('pill-status').textContent = m.pill;
  pill.classList.toggle('live', Boolean(m.running) && m.online);
  pill.classList.toggle('warn', state === 'fault');
  const ledClass = m.online ? 'led on' : 'led off';
  document.getElementById('pill-led').className = ledClass;
  document.getElementById('band-led').className = (m.online ? 'led on' : 'led off') + (state === 'starting' || state === 'arrival' ? ' blink' : '');

  /* ---------- readouts ---------- */
  const spark = (() => {
    const pts = [61.2, 61.4, 61.9, 62.3, 62.1, 61.8, 62.6, 63.1, 63.4, 63.0, 62.4, 62.2, 61.9, 61.9];
    const min = Math.min(...pts), max = Math.max(...pts), w = 100, h = 34;
    const d = pts.map((v, i) => `${i ? 'L' : 'M'}${(i / (pts.length - 1) * w).toFixed(1)} ${(h - 4 - (v - min) / (max - min || 1) * (h - 8)).toFixed(1)}`).join(' ');
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path class="base" d="M0 ${h - 1} H${w}"/><path d="${d}"/></svg>`;
  })();
  const ro = (label, value, cls = '', extra = '') => `<div class="ro ${cls}"><small>${label}</small><b>${value}</b>${extra}</div>`;
  document.getElementById('readouts').innerHTML = state === 'connecting'
    ? '<span class="skel ro"></span><span class="skel ro temp"></span><span class="skel ro"></span>'
    : (m.project ? ro('Status', 'GPGPU testing', 'cy', '<span class="when">In use by the GPGPU team</span>')
      : m.running ? ro('Status', m.status, 'cy', `<span class="when">${name(m.running)}, ${m.mine === m.running ? 'your session' : 'another visitor'}</span>`)
      : ro('Status', m.status, state === 'fault' ? 'warn' : '', state === 'fault' ? `<span class="when">${m.fault}</span>` : '<span class="when">Nothing running</span>'))
    + (m.temp == null ? ro('Temperature', 'No reading', 'dim temp') : ro('Temperature', `${m.temp.toFixed(1)} °C`, state === 'fault' ? 'warn temp' : 'temp', spark + `<span class="when">Die, read 2 s ago</span>`))
    + ro('Queue', m.queue == null ? '…' : m.queue === 0 ? 'Empty' : `${m.queue} waiting`, m.queue ? '' : 'dim', m.queue ? `<span class="when">${m.queue === 1 ? 'One visitor' : 'Visitors'} after the current one</span>` : '<span class="when">Nobody waiting</span>');

  /* ---------- session panel or stage ---------- */
  if (state === 'connecting') {
    document.querySelector('.ident').innerHTML = '<span class="skel h" style="width:46%"></span><span class="skel t"></span>';
    document.querySelector('.what').outerHTML = '<span class="skel p"></span>';
    document.getElementById('pill-status').textContent = 'Connecting';
  }
  const hero = document.querySelector('.hero');
  const board = document.getElementById('boardpanel');
  const sess = document.getElementById('session');
  const stageSvg = T['gpgpu-nbody'].replace('viewBox="0 0 120 76"', 'viewBox="0 0 120 76" style="aspect-ratio:120/76"').replace('fill="#183539"', 'fill="#06181b"');
  let html = '';
  if (state === 'connecting') html = `<h2>Your session</h2><span class="skel h"></span><span class="skel p"></span><span class="skel p2"></span><span class="skel btn"></span>`;
  else if (state === 'offline') html = `<h2>Your session</h2><p class="big">Status unavailable</p><p class="sub">The lab can't reach the board right now. This page reconnects on its own; nothing to do on your side.</p>`;
  else if (state === 'fault') { sess.classList.add('warn'); html = `<h2>Your session</h2><p class="demo-name">Board fault: ${m.fault.toLowerCase()}</p><p class="sub">The board recovers on its own, usually within a minute. Demos reopen when it does.</p>`; }
  else if (state === 'project') html = `<h2>Your session</h2><p class="big">In use for GPGPU testing</p><p class="sub">My colleagues are using the board to test our GPGPU right now. Demos reopen as soon as it's free; this page updates on its own.</p>`;
  else if (state === 'idle') html = `<h2>Your session</h2><p class="big">The board is free</p><p class="sub">Pick a demo below and the board is programmed for you right away. You keep it as long as nobody is waiting.</p><a class="btn live" href="#demos">Choose a demo</a>`;
  else if (state === 'busy') html = `<h2>Your session</h2><p class="big">Someone is on the board</p><p class="sub">${name(m.running)} is running for another visitor, and one more is waiting. Pick a demo to join the queue; each turn is 5 minutes once somebody waits.</p><a class="btn live" href="#demos">Choose a demo</a>`;
  else if (state === 'arrival') html = `<h2>Your session</h2><p class="pulseline"><i class="led on blink"></i><span class="demo-name">Programming the board for ${name(m.mine)}</span></p><p class="sub">Opened from ${m.from}. The demo appears here as soon as the board is ready, in under a minute.</p><div class="row"><button class="btn">Cancel</button></div>`;
  else if (state === 'queued') html = `<h2>Your session</h2><p class="big"><em>2nd</em> of 3 waiting</p><p class="sub">For <span class="demo-name">${name(m.mine)}</span></p><p class="sub">Estimated start in <b>${dur(m.eta)}</b>. Each visitor gets 5 minutes once somebody is waiting.</p><div class="bar" style="--w:46%"><i></i></div><div class="row"><button class="btn">Leave the queue</button></div>`;
  else if (state === 'starting') html = `<h2>Your session</h2><p class="pulseline"><i class="led on blink"></i><span class="demo-name">Programming the board for ${name(m.mine)}</span></p><p class="sub">The bitstream is loading and the processor is booting. The demo appears here as soon as the board is ready.</p><div class="row"><button class="btn">Cancel</button></div>`;
  else if (state === 'ending') html = `<h2>Your session</h2><p class="big">Resetting the board</p><p class="sub">Your ${name(m.mine)} session has ended. The board resets for the next visitor; you can start another demo in a moment.</p>`;
  else if (isActive) {
    hero.classList.add('stage-first');
    board.classList.add('compact');
    sess.remove();
    const stage = document.createElement('div');
    stage.className = 'stage'; stage.id = 'session';
    stage.innerHTML = `<div class="sbar"><span class="who"><i class="led on"></i>${name(m.mine)}</span>${m.left != null ? `<span class="left"><b>${dur(m.left)}</b> left, someone is waiting</span>` : ''}<div class="acts"><button class="btn s">Fullscreen</button><button class="btn s">Open in a new tab</button><button class="btn s p">End session</button></div></div><div class="frame">${stageSvg}<span class="note">The demo's own page runs here</span></div>`;
    hero.prepend(stage);
    hero.appendChild(board);
    document.querySelector('.topbar nav a[href="#session"]').textContent = 'Your demo';
  }
  if (html) sess.innerHTML = html;

  /* ---------- demo rows ---------- */
  const busy = Boolean(m.running) || Boolean(m.mine);
  document.getElementById('demolist').innerHTML = state === 'connecting' ? DEMOS.slice(0, 4).map(() => `<article class="demo loading" aria-hidden="true"><div class="thumb"></div><div class="text"><span class="skel h" style="width:55%;height:22px"></span><span class="skel p"></span><span class="skel t"></span></div><div class="act"><span class="skel btn" style="width:84px;height:40px"></span></div></article>`).join('') : DEMOS.map(([id, nm, desc, kind]) => {
    const chosen = m.mine === id && (state === 'arrival' || state === 'queued' || state === 'starting' || isActive);
    let btn = `<button class="btn live">Start</button>`, note = '';
    if (state === 'connecting' || state === 'offline' || state === 'fault') { btn = `<button class="btn" disabled>Start</button>`; note = state === 'fault' ? 'Until the board recovers' : 'Unavailable'; }
    else if (m.project) { btn = `<button class="btn" disabled>Start</button>`; note = 'In use for GPGPU testing'; }
    else if (chosen) { btn = `<button class="btn" disabled>${isActive ? 'Running' : state === 'queued' ? 'In your queue' : 'Starting'}</button>`; }
    else if (busy) { btn = `<button class="btn" disabled>Start</button>`; note = m.mine ? 'One session at a time' : 'Joins the queue'; if (!m.mine) btn = `<button class="btn live">Start</button>`; }
    return `<article class="demo ${chosen ? 'chosen' : ''}"><div class="thumb">${T[id]}</div><div class="text"><h3>${nm}</h3><p>${desc}</p><div class="kind"><span class="tag">${kind}</span></div></div><div class="act">${btn}${note ? `<small>${note}</small>` : ''}</div></article>`;
  }).join('');

  /* ---------- recent ---------- */
  document.getElementById('reclist').innerHTML = state === 'connecting' ? Array.from({ length: 3 }, () => `<div class="rec loading" aria-hidden="true"><span class="dot"></span><span><span class="skel p" style="width:40%"></span><span class="skel t" style="margin-top:6px"></span></span><span class="skel t"></span></div>`).join('')
    : RECENT.map(([id, why, t, cls]) => `<div class="rec"><span class="dot ${cls}"></span><span><b>${name(id)}</b><small>${why}</small></span><time>Today ${t}</time></div>`).join('');

  /* ---------- the copper trace: arrives from the top edge, lands on the board, then runs the gutter ---------- */
  const host = document.querySelector('[data-trace]');
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('class', 'trace'); svg.setAttribute('aria-hidden', 'true');
  const mk = (cls) => { const p = document.createElementNS(NS, 'path'); p.setAttribute('class', cls); svg.appendChild(p); return p; };
  const ghost = mk('t-ghost'), drawn = mk('t-drawn'), pulse = mk('t-pulse');
  const deco = document.createElementNS(NS, 'g'); svg.appendChild(deco);
  host.prepend(svg);
  if (!reduce) document.documentElement.classList.add('rv');

  let total = 0, samples = [], padLens = [], secs = [], shown = 0, target = 0, padItems = [];
  function build() {
    const hb = host.getBoundingClientRect();
    const railX = parseFloat(getComputedStyle(host).getPropertyValue('--trace-x')) || 14;
    const rel = r => ({ x: r.left - hb.left, y: r.top - hb.top, w: r.width, h: r.height });
    const padEls = [...host.querySelectorAll('[data-pad]')].filter(e => e.offsetParent);
    secs = padEls.map(e => e.closest('section'));
    const pts = padEls.map(e => { const r = rel(e.getBoundingClientRect()); return { x: railX, y: r.y + Math.min(r.h / 2, 24), edge: r.x }; });
    const startY = -40; // from above the page: the current comes in from the portfolio
    let d = `M${railX} ${startY} V${pts[pts.length - 1].y}`;
    [ghost, drawn, pulse].forEach(p => p.setAttribute('d', d));
    svg.setAttribute('width', hb.width); svg.setAttribute('height', host.offsetHeight); svg.setAttribute('viewBox', `0 0 ${hb.width} ${host.offsetHeight}`);
    total = drawn.getTotalLength();
    samples = []; for (let l = 0; l <= total; l += 6) samples.push([l, drawn.getPointAtLength(l).y]);
    padLens = pts.map(p => { const s = samples.find(s => s[1] >= p.y - 1); return s ? s[0] : total; });
    // pads, plus a stub into the board's band (the trace enters the component) and vias beside each pad
    deco.innerHTML = pts.map((p, i) => {
      const stub = i === 0 ? `<path class="t-stub" data-i="${i}" d="M${p.x + 8} ${p.y} H${p.edge - 2}"/>` : `<path class="t-stub" data-i="${i}" d="M${p.x + 8} ${p.y - 18} H${p.x + 18} M${p.x + 8} ${p.y + 18} H${p.x + 18}"/>`;
      const vias = i === 0 ? '' : `<circle class="t-via" data-i="${i}" cx="${p.x + 21}" cy="${p.y - 18}" r="3"/><circle class="t-via" data-i="${i}" cx="${p.x + 21}" cy="${p.y + 18}" r="3"/>`;
      return stub + vias + `<circle class="t-pad" data-i="${i}" cx="${p.x}" cy="${p.y}" r="8.5"/>`;
    }).join('');
    padItems = [...deco.querySelectorAll('[data-i]')];
    drawn.style.strokeDasharray = `${total} ${total}`;
    pulse.style.strokeDasharray = `44 ${total + 44}`;
    measure();
    if (reduce) shown = total;
  }
  function lenAtY(y) { if (!samples.length) return 0; for (const [l, sy] of samples) if (sy >= y) return l; return total; }
  function measure() { const hb = host.getBoundingClientRect(); target = lenAtY(innerHeight * 0.78 - hb.top); }
  let pos = 0, last = performance.now();
  function frame(now) {
    const dt = Math.min(now - last, 50); last = now;
    shown += (target - shown) * (reduce ? 1 : 0.12);
    drawn.style.strokeDashoffset = total - shown;
    padItems.forEach(el => el.classList.toggle('on', padLens[+el.dataset.i] <= shown + 2));
    secs.forEach((sec, i) => { if (sec && !sec.classList.contains('lit') && (padLens[i] <= shown + 2 || sec.getBoundingClientRect().top < innerHeight * 0.7)) sec.classList.add('lit'); });
    if (!reduce && m.online && shown > 60) { pos += dt * 0.52; if (pos > shown + 44) pos = 0; pulse.style.strokeDashoffset = 44 - pos; pulse.style.opacity = 1; }
    else pulse.style.opacity = 0;
    requestAnimationFrame(frame);
  }
  addEventListener('scroll', measure, { passive: true });
  let queued = false, lastW = 0, lastH = 0;
  const schedule = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; if (host.offsetWidth === lastW && host.offsetHeight === lastH) return; lastW = host.offsetWidth; lastH = host.offsetHeight; build(); }); };
  new ResizeObserver(schedule).observe(host);
  addEventListener('load', () => { lastW = 0; schedule(); });
  schedule();
  requestAnimationFrame(frame);
})();
