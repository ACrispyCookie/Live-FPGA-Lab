// The page: top bar, the trace, the hero (board and the visitor's session), the demos and the recent sessions.
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { autostart, withoutStart } from './autostart.ts';
import { BoardPanel } from './components/BoardPanel.tsx';
import { DemoList } from './components/DemoList.tsx';
import { Footer } from './components/Footer.tsx';
import { RecentSessions } from './components/RecentSessions.tsx';
import { SessionPanel } from './components/SessionPanel.tsx';
import { Stage } from './components/Stage.tsx';
import { Toasts } from './components/Toasts.tsx';
import { TopBar } from './components/TopBar.tsx';
import { Trace } from './components/Trace.tsx';
import { mockState } from './dev/fixtures.ts';
import { copy } from './lab/copy.ts';
import { demoName, heroLayout, phase, tabTitle, timeLeft } from './lab/derive.ts';
import { initialState, isLive, reduce } from './lab/reducer.ts';
import { needsScroll } from './lab/scroll.ts';
import { useLabSocket } from './lab/socket.ts';
import { useLayoutTransitionDispatch } from './lab/useLayoutTransitionDispatch.ts';
import type { Action, LabState } from './lab/types.ts';

const TOAST_TTL_MS = 5200;
const reducer = (state: LabState, action: Action) => reduce(state, action, Date.now());
const MOCK = import.meta.env.VITE_MOCK_STATES === '1';

declare global { interface Window { __labDispatches?: string[] } }

function arrivalNote(): string | null {
  try {
    if (!document.referrer) return null;
    const host = new URL(document.referrer).hostname;
    if (host === location.hostname) return null;
    return host.endsWith('njason.dev') ? copy.session.opened.portfolio : copy.session.opened.link;
  } catch {
    return null;
  }
}

export function App() {
  const [mock] = useState(() => mockState());
  const [state, rawDispatch] = useReducer(reducer, mock ?? initialState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const getState = useCallback(() => stateRef.current, []);
  // actions that rearrange the hero animate it; the rest (and ticks, toasts) dispatch as they are
  const heroRef = useRef<HTMLElement>(null);
  const heroVisible = useCallback(() => { const r = heroRef.current?.getBoundingClientRect(); return !!r && r.bottom > 0 && r.top < innerHeight; }, []);
  const { dispatch, settled } = useLayoutTransitionDispatch(rawDispatch, getState, heroVisible);
  const { send } = useLabSocket(dispatch, !mock);
  const [sessionVisible, setSessionVisible] = useState(true);
  const [arrival, setArrival] = useState<string | null>(null);
  const autostartRef = useRef(false);
  const toastTimers = useRef<Record<string, number>>({});
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => dispatch({ type: 'tick', now: Date.now() }), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    for (const toast of state.toasts) {
      if (toastTimers.current[toast.id]) continue;
      toastTimers.current[toast.id] = window.setTimeout(() => { delete toastTimers.current[toast.id]; dispatch({ type: 'toast.dismissed', id: toast.id }); }, TOAST_TTL_MS);
    }
  }, [state.toasts]);

  useEffect(() => {
    const el = heroRef.current;
    if (!el || !('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver(([entry]) => setSessionVisible(entry.isIntersecting), { rootMargin: '-62px 0px 0px 0px', threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Take the visitor to their session panel: scroll only if it isn't fully in view under the bar, then move focus
  // to it and ring it once. Runs after the render, so the panel is measured in its new state.
  const revealSession = useCallback(() => {
    settled().then(() => requestAnimationFrame(() => {
      const panel = heroRef.current?.querySelector<HTMLElement>('.session');
      if (!panel) return;
      const bar = document.querySelector('.topbar')?.getBoundingClientRect().height ?? 0;
      const r = panel.getBoundingClientRect();
      if (needsScroll(r.top, r.bottom, innerHeight, bar)) {
        const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
        panel.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });
      }
      headingRef.current?.focus({ preventScroll: true });
      setFlash(false);
      requestAnimationFrame(() => setFlash(true));
    }));
  }, [settled]);

  const onStart = useCallback((demoId: string) => {
    if (state.requesting || isLive(state.session)) return;
    const requestId = send('session.create', { demo_id: demoId });
    if (MOCK) (window.__labDispatches ||= []).push('start.requested');
    dispatch({ type: 'start.requested', demoId, requestId });
    revealSession();
  }, [send, state.requesting, state.session, revealSession]);

  const onEnd = useCallback(() => {
    if (!isLive(state.session)) return;
    send('session.end', { session_id: state.session.id });
    dispatch({ type: 'end.requested' });
  }, [send, state.session]);

  // ?start=<demo id> (the portfolio's "Run the demo"): as if the visitor pressed Start, once per page load.
  useEffect(() => {
    if (!state.ready || autostartRef.current) return;
    autostartRef.current = true;
    const next = autostart(location.search, { demos: state.demos, hasSession: isLive(state.session), reserved: state.board?.mode === 'project' });
    if (next.action === 'none') return;
    history.replaceState(history.state, '', withoutStart(location.pathname + location.search, location.hash));
    if (next.action === 'start') {
      setArrival(arrivalNote());
      onStart(next.demo.id);
    } else dispatch({ type: 'ui.message', level: 'warn', message: next.message });
  }, [state.ready, state.demos, state.session, state.board, onStart]);

  const p = phase(state);
  const title = tabTitle(state);
  useEffect(() => { document.title = title; }, [title]);

  // a queued visitor's turn: bring the panel back into view wherever they are on the page
  const prevPhase = useRef(p);
  useEffect(() => {
    if (prevPhase.current === 'queued' && p === 'starting') revealSession();
    prevPhase.current = p;
  }, [p, revealSession]);
  const online = state.ready && state.socket === 'connected' && p !== 'offline';
  const layout = heroLayout(state);
  const staged = layout === 'stage';
  const sessionPanel = (lead: boolean) => (
    <SessionPanel state={state} lead={lead} arrival={arrival} onCancel={onEnd} onEnd={onEnd} onRetry={onStart} headingRef={headingRef} flash={flash} onFlashEnd={() => setFlash(false)} />
  );

  // The demo appears where the visitor is looking: when the stage arrives, the page scrolls to its top.
  useEffect(() => {
    if (!staged) return;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    settled().then(() => heroRef.current?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' }));
  }, [staged, settled]);

  return (
    <>
      <Toasts toasts={state.toasts} onDismiss={(id) => dispatch({ type: 'toast.dismissed', id })} />
      <TopBar state={state} sessionVisible={sessionVisible} />
      <div className="wrap" data-trace>
        <Trace online={online} layoutKey={layout} />
        <main>
          {/* One slot for the visitor: the board leads until they start something; from then on their session does, and
              it becomes the stage while their demo is live. DOM order follows what is seen. */}
          <section className={`hero lay-${layout}`} id="session-hero" ref={heroRef} aria-label="The board and your session">
            {layout === 'stage' ? <>
              <Stage state={state} session={state.session!} demoName={demoName(state.demos, state.session!.demo_id)} timeLeft={timeLeft(state.session, state.now)} onEnd={onEnd} />
              <BoardPanel state={state} compact />
            </> : layout === 'session-first' ? <>
              {sessionPanel(true)}
              <BoardPanel state={state} compact />
            </> : <>
              <BoardPanel state={state} lead />
              {sessionPanel(false)}
            </>}
          </section>
          <section className="sec" id="demos">
            <h2 data-pad>{copy.demos.heading}</h2>
            <p className="lead">{copy.demos.lead}</p>
            <DemoList state={state} onStart={onStart} />
          </section>
          <section className="sec" id="recent">
            <h2 data-pad>{copy.recent.heading}</h2>
            <p className="lead">{copy.recent.lead}</p>
            <RecentSessions state={state} />
          </section>
        </main>
      </div>
      <Footer />
    </>
  );
}
