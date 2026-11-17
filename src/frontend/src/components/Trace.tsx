// The copper trace: it enters from the top edge (the current comes from the portfolio), lands on the board's
// band with a short stub, then runs the gutter past a gold pad at every section heading. It draws as you
// scroll, pads light when reached, sections switch on, and a cyan pulse runs while the board is online.
// Ported from docs/superpowers/mocks/lab/lab.js. Reduced motion: fully drawn, pads lit, no pulse.
import { useEffect, useRef } from 'react';

const NS = 'http://www.w3.org/2000/svg';
const PULSE_LEN = 44;
const PULSE_SPEED = 0.52; // px per ms
const PAD_RADIUS = 8.5;

export function Trace({ online, layoutKey }: { online: boolean; layoutKey: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const onlineRef = useRef(online);
  const shownRef = useRef(0);
  onlineRef.current = online;

  useEffect(() => {
    const svg = svgRef.current;
    const host = svg?.parentElement;
    if (!svg || !host) return;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce) document.documentElement.classList.add('rv');

    const mk = (cls: string) => { const p = document.createElementNS(NS, 'path'); p.setAttribute('class', cls); svg.appendChild(p); return p; };
    const ghost = mk('t-ghost'), drawn = mk('t-drawn'), pulse = mk('t-pulse');
    const deco = document.createElementNS(NS, 'g');
    svg.appendChild(deco);

    let total = 0, samples: Array<[number, number]> = [], padLens: number[] = [], secs: Array<Element | null> = [];
    let target = 0, padItems: Element[] = [], raf = 0, pos = 0, last = performance.now();
    let shown = reduce ? Infinity : shownRef.current;

    function build() {
      const hb = host!.getBoundingClientRect();
      const railX = parseFloat(getComputedStyle(host!).getPropertyValue('--trace-x')) || 18.5;
      const rel = (r: DOMRect) => ({ x: r.left - hb.left, y: r.top - hb.top, w: r.width, h: r.height });
      const padEls = [...host!.querySelectorAll<HTMLElement>('[data-pad]')].filter((e) => e.offsetParent);
      if (!padEls.length) return;
      secs = padEls.map((e) => e.closest('section.sec'));
      const pts = padEls.map((e) => { const r = rel(e.getBoundingClientRect()); return { x: railX, y: r.y + Math.min(r.h / 2, 24), edge: r.x }; });
      const d = `M${railX} -40 V${pts[pts.length - 1].y}`;
      [ghost, drawn, pulse].forEach((p) => p.setAttribute('d', d));
      svg!.setAttribute('width', String(hb.width));
      svg!.setAttribute('height', String(host!.offsetHeight));
      svg!.setAttribute('viewBox', `0 0 ${hb.width} ${host!.offsetHeight}`);
      total = drawn.getTotalLength();
      samples = [];
      for (let l = 0; l <= total; l += 6) samples.push([l, drawn.getPointAtLength(l).y]);
      padLens = pts.map((p) => { const s = samples.find((s) => s[1] >= p.y - 1); return s ? s[0] : total; });
      deco.innerHTML = pts.map((p, i) => {
        const stub = i === 0
          ? `<path class="t-stub" data-i="${i}" d="M${p.x + 8} ${p.y} H${p.edge - 2}"/>`
          : `<path class="t-stub" data-i="${i}" d="M${p.x + 8} ${p.y - 18} H${p.x + 18} M${p.x + 8} ${p.y + 18} H${p.x + 18}"/>`;
        const vias = i === 0 ? '' : `<circle class="t-via" data-i="${i}" cx="${p.x + 21}" cy="${p.y - 18}" r="3"/><circle class="t-via" data-i="${i}" cx="${p.x + 21}" cy="${p.y + 18}" r="3"/>`;
        return `${stub}${vias}<circle class="t-pad" data-i="${i}" cx="${p.x}" cy="${p.y}" r="${PAD_RADIUS}"/>`;
      }).join('');
      padItems = [...deco.querySelectorAll('[data-i]')];
      drawn.style.strokeDasharray = `${total} ${total}`;
      pulse.style.strokeDasharray = `${PULSE_LEN} ${total + PULSE_LEN}`;
      measure();
      if (reduce) shown = total;
    }
    function lenAtY(y: number) { if (!samples.length) return 0; for (const [l, sy] of samples) if (sy >= y) return l; return total; }
    // Under reduced motion the whole trace is drawn and every pad lit, whatever the scroll position.
    function measure() { const hb = host!.getBoundingClientRect(); target = reduce ? total : lenAtY(innerHeight * 0.78 - hb.top); }
    function frame(now: number) {
      const dt = Math.min(now - last, 50); last = now;
      if (!Number.isFinite(shown)) shown = total;
      shown += (target - shown) * (reduce ? 1 : 0.12);
      shownRef.current = shown;
      drawn.style.strokeDashoffset = String(total - shown);
      padItems.forEach((el) => el.classList.toggle('on', padLens[+((el as HTMLElement).dataset.i || 0)] <= shown + 2));
      secs.forEach((sec, i) => { if (sec && !sec.classList.contains('lit') && padLens[i] <= shown + 2) sec.classList.add('lit'); });
      if (!reduce && onlineRef.current && shown > 60) {
        pos += dt * PULSE_SPEED;
        if (pos > shown + PULSE_LEN) pos = 0;
        pulse.style.strokeDashoffset = String(PULSE_LEN - pos);
        pulse.style.opacity = '1';
      } else pulse.style.opacity = '0';
      raf = requestAnimationFrame(frame);
    }
    // Fallback so nothing stays hidden: a section also switches on once 30 % of it is on screen.
    const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add('lit'); }), { threshold: 0.3 });
    host.querySelectorAll('section.sec').forEach((s) => io.observe(s));

    let queued = false, lastW = 0, lastH = 0;
    const schedule = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        if (host!.offsetWidth === lastW && host!.offsetHeight === lastH) return;
        lastW = host!.offsetWidth; lastH = host!.offsetHeight;
        build();
      });
    };
    const ro = new ResizeObserver(schedule);
    ro.observe(host);
    addEventListener('scroll', measure, { passive: true });
    schedule();
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      removeEventListener('scroll', measure);
      svg.replaceChildren();
    };
  }, [layoutKey]);

  return <svg ref={svgRef} className="trace" aria-hidden="true" />;
}
