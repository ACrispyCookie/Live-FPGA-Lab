// The page: top bar, the trace, the hero (board and the visitor's session), the demos and the recent sessions.
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { autostart, withoutStart } from './autostart.ts';
import { BoardPanel } from './components/BoardPanel.tsx';
import { DemoList } from './components/DemoList.tsx';
import { RecentSessions } from './components/RecentSessions.tsx';
import { SessionPanel } from './components/SessionPanel.tsx';
import { Toasts } from './components/Toasts.tsx';
import { TopBar } from './components/TopBar.tsx';
import { Trace } from './components/Trace.tsx';
import { mockState } from './dev/fixtures.ts';
import { copy } from './lab/copy.ts';
import { phase } from './lab/derive.ts';
import { initialState, isLive, reduce } from './lab/reducer.ts';
import { useLabSocket } from './lab/socket.ts';
import type { Action, LabState } from './lab/types.ts';

const TOAST_TTL_MS = 5200;
const PHONE = '(max-width: 760px)';
const reducer = (state: LabState, action: Action) => reduce(state, action, Date.now());

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
  const [state, dispatch] = useReducer(reducer, mock ?? initialState);
  const { send } = useLabSocket(dispatch, !mock);
  const heroRef = useRef<HTMLElement>(null);
  const [sessionVisible, setSessionVisible] = useState(true);
  const [arrival, setArrival] = useState<string | null>(null);
  const autostartRef = useRef(false);
  const toastTimers = useRef<Record<string, number>>({});

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

  const scrollToSession = useCallback(() => {
    if (!matchMedia(PHONE).matches) return;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    heroRef.current?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });
  }, []);

  const onStart = useCallback((demoId: string) => {
    if (state.requesting || isLive(state.session)) return;
    const requestId = send('session.create', { demo_id: demoId });
    dispatch({ type: 'start.requested', demoId, requestId });
    scrollToSession();
  }, [send, state.requesting, state.session, scrollToSession]);

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
  const online = state.ready && state.socket === 'connected' && p !== 'offline';

  return (
    <>
      <Toasts toasts={state.toasts} onDismiss={(id) => dispatch({ type: 'toast.dismissed', id })} />
      <TopBar state={state} sessionVisible={sessionVisible} />
      <div className="wrap" data-trace>
        <Trace online={online} layoutKey={p === 'active' ? 'stage' : 'panel'} />
        <main>
          <section className="hero" id="session-hero" ref={heroRef} aria-label="The board and your session">
            <BoardPanel state={state} />
            <SessionPanel state={state} arrival={arrival} onCancel={onEnd} onEnd={onEnd} />
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
        <footer className="foot">
          <span>{copy.site.partOf} <a href={copy.site.home}>njason.dev</a></span>
          <a href={copy.site.source}>{copy.site.sourceLabel}</a>
        </footer>
      </div>
    </>
  );
}
