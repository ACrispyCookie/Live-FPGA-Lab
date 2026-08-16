import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Board = {
  device_id?: string | null;
  device_name?: string | null;
  status?: string | null;
  bitstream_id?: string | null;
  telemetry?: { temperature_c?: number | null } | null;
  faults?: Array<{ type?: string; message?: string }>;
} | null;

type Demo = { id: string; name: string; description?: string };
type QueueState = { length: number; position: number | null; active_expires_at?: string | null };
type Session = {
  id: string;
  demo_id: string;
  status: 'queued' | 'starting' | 'active' | 'ending' | 'ended';
  created_at: string;
  started_at?: string | null;
  expires_at?: string | null;
  ended_at?: string | null;
  end_reason?: string | null;
  demo_url?: string | null;
} | null;

type WsState = 'connecting' | 'connected' | 'reconnecting';
const CONTENDED_SECONDS = 300;

function titleCase(value?: string | null) {
  return String(value || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function secondsUntil(value?: string | null) {
  if (!value) return null;
  return Math.max(0, Math.round((Date.parse(value) - Date.now()) / 1000));
}

function duration(seconds: number | null) {
  if (seconds == null) return '—';
  const s = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(s / 60);
  const rest = s % 60;
  return minutes ? `${minutes}m ${String(rest).padStart(2, '0')}s` : `${rest}s`;
}

function App() {
  const [wsState, setWsState] = useState<WsState>('connecting');
  const [board, setBoard] = useState<Board>(null);
  const [demos, setDemos] = useState<Demo[]>([]);
  const [queue, setQueue] = useState<QueueState>({ length: 0, position: null, active_expires_at: null });
  const [session, setSession] = useState<Session>(null);
  const [recentSessions, setRecentSessions] = useState<NonNullable<Session>[]>([]);
  const [nowTick, setNowTick] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<number | undefined>(undefined);
  const attemptsRef = useRef(0);
  const requestRef = useRef(0);

  useEffect(() => {
    const timer = window.setInterval(() => setNowTick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let closed = false;
    function connect() {
      if (closed) return;
      setWsState(attemptsRef.current ? 'reconnecting' : 'connecting');
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${location.host}/api/ws`, 'fpga-demo.v1');
      wsRef.current = ws;
      ws.addEventListener('open', () => {
        attemptsRef.current = 0;
        setWsState('connected');
      });
      ws.addEventListener('message', (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'state.initial') {
          setBoard(msg.board);
          setDemos(msg.demos || []);
          setQueue(msg.queue || { length: 0, position: null });
          setSession(msg.session);
          setRecentSessions(msg.recent_sessions || []);
          return;
        }
        if (msg.type === 'board.updated') setBoard(msg.board);
        if (msg.type === 'queue.updated') setQueue(msg.queue || { length: 0, position: null });
        if (msg.type === 'session.updated') {
          setSession(msg.session);
          if (msg.session) setRecentSessions((sessions) => mergeSession(sessions, msg.session));
        }
        if (msg.type === 'recent_sessions.updated') setRecentSessions(msg.sessions || []);
      });
      ws.addEventListener('close', () => {
        if (closed || wsRef.current !== ws) return;
        attemptsRef.current += 1;
        const delay = Math.min(10000, 350 * 2 ** Math.min(attemptsRef.current, 5));
        setWsState('reconnecting');
        retryRef.current = window.setTimeout(connect, delay);
      });
      ws.addEventListener('error', () => ws.close());
    }
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryRef.current);
      wsRef.current?.close(1000, 'page unload');
    };
  }, []);

  function send(type: string, payload: Record<string, unknown> = {}) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type, request_id: `${Date.now()}-${++requestRef.current}`, ...payload }));
  }

  const liveSession = session && session.status !== 'ended' ? session : null;
  const activeTimeLeft = liveSession?.status === 'active' ? secondsUntil(liveSession.expires_at) : null;
  const queueEta = useMemo(() => {
    if (!queue.position || !queue.active_expires_at) return null;
    return secondsUntil(queue.active_expires_at)! + Math.max(0, queue.position - 1) * CONTENDED_SECONDS;
  }, [queue.position, queue.active_expires_at, nowTick]);
  const visibleBoardSession = liveSession?.status === 'active' || liveSession?.status === 'starting'
    ? liveSession
    : recentSessions.find((item) => item.status === 'active' || item.status === 'starting') || null;
  const selectedDemo = demos.find((demo) => demo.id === liveSession?.demo_id);
  const boardDemo = demos.find((demo) => demo.id === visibleBoardSession?.demo_id);
  const faults = board?.faults || [];
  const boardStatus = board?.status || 'unknown';
  const hasBoardFault = boardStatus === 'fault' || boardStatus === 'offline' || faults.length > 0;
  const healthState = boardStatus === 'fault' || faults.length ? 'bad' : boardStatus === 'offline' ? 'warn' : 'ok';
  const boardDotClass = boardStatus === 'running' ? 'ok' : boardStatus === 'fault' || boardStatus === 'offline' ? 'bad' : 'warn';
  const sessionHelp = sessionCopy(liveSession, activeTimeLeft, queueEta);
  const isActiveUser = liveSession?.status === 'active';
  const queueDisplayEta = !hasBoardFault && !isActiveUser && queue.position ? queueEta : null;
  const queueEtaLabel = hasBoardFault ? 'Fault detected' : duration(queueDisplayEta);
  const queueBarPct = !hasBoardFault && !isActiveUser && queue.position && queueDisplayEta != null
    ? Math.max(0, Math.min(100, (queueDisplayEta / Math.max(1, queue.position * CONTENDED_SECONDS)) * 100))
    : 0;

  if (wsState !== 'connected') {
    return <SkeletonPage state={wsState} />;
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>Live FPGA Lab</h1>
          <p>ECE hardware demos served from a homelab bench — live board access and control.</p>
        </div>
        <Pill tone={wsState === 'connected' ? 'ok' : 'warn'}>{titleCase(wsState)}</Pill>
      </header>

      <div className="hero-grid">
        <Section title="Board" className="board-section">
          <div className="board-grid">
            <InfoRow tone={boardDotClass} label={titleCase(boardStatus)} value={formatTemp(board)} />
            <InfoRow tone={visibleBoardSession ? 'ok' : 'neutral'} label={board?.device_name || board?.device_id || 'Board'} value={runningDemoLabel(visibleBoardSession, boardDemo)} />
            <InfoRow tone={healthState} label="Health" value={healthSummary(healthState, faults)} />
          </div>
        </Section>

        <Section title="Available demos" className="demos-section">
          <div className="demo-grid">
            {demos.length ? demos.map((demo) => (
              <article className="demo-card" key={demo.id}>
                <div>
                  <strong>{demo.name}</strong>
                  {demo.description && <span>{demo.description}</span>}
                </div>
                <button disabled={Boolean(liveSession)} onClick={() => send('session.create', { demo_id: demo.id })}>
                  {liveSession ? 'Busy' : 'Start'}
                </button>
              </article>
            )) : <div className="empty">No demos are currently available.</div>}
          </div>
        </Section>
      </div>

      <div className="lower-grid">
        <div className="queue-column">
          <Section title="Queue" className="queue-section">
            <div className="queue-panel">
              <div className="queue-count"><span>Your place</span><strong>{isActiveUser ? '—' : queue.position ?? '—'}</strong><small>/ {queue.length} users</small></div>
              <div className={`eta-card ${hasBoardFault ? 'fault' : ''}`}><span>ETA</span><strong>{queueEtaLabel}</strong><div className="queue-progress"><div style={{ width: `${queueBarPct}%` }} /></div></div>
            </div>
          </Section>
          <RecentSessions sessions={recentSessions} demos={demos} />
        </div>

        <Section title="Demo status" className="status-section">
          <div className="status-panel">
            <div className="status-orb"><span className={sessionTone(liveSession?.status)} /></div>
            <div className="status-copy">
              <div className="status-topline"><Pill tone={sessionTone(liveSession?.status)}>{sessionLabel(liveSession)}</Pill><button className="danger end-button" disabled={!liveSession} onClick={() => liveSession && send('session.end', { session_id: liveSession.id })}>End</button></div>
              <h2>{selectedDemo?.name || 'No demo running'}</h2>
              <p>{sessionHelp}</p>
            </div>
          </div>
          {liveSession?.status === 'active' && liveSession.demo_url && (
            <iframe title={`${selectedDemo?.name || 'Demo'} iframe`} src={liveSession.demo_url} />
          )}
        </Section>
      </div>
    </main>
  );
}


function SkeletonPage({ state }: { state: WsState }) {
  return (
    <main className="shell skeleton-shell">
      <header className="topbar">
        <div>
          <h1>Live FPGA Lab</h1>
          <p>{state === 'reconnecting' ? 'Connection lost. Reconnecting…' : 'Connecting to the homelab board…'}</p>
        </div>
        <Pill tone="warn">{titleCase(state)}</Pill>
      </header>
      <div className="hero-grid">
        <SkeletonSection title="Board" lines={3} />
        <SkeletonSection title="Available demos" cards={3} />
      </div>
      <div className="lower-grid">
        <div className="queue-column">
          <SkeletonSection title="Queue" lines={2} />
          <SkeletonSection title="Recent sessions" lines={3} compact />
        </div>
        <SkeletonSection title="Demo status" hero />
      </div>
    </main>
  );
}

function SkeletonSection({ title, lines = 0, cards = 0, hero = false, compact = false }: { title: string; lines?: number; cards?: number; hero?: boolean; compact?: boolean }) {
  return (
    <section className={`section skeleton-section ${compact ? 'compact-skeleton' : ''}`}>
      <h2>{title}</h2>
      {hero && <div className="skeleton-hero"><div /><span /><span /></div>}
      {lines > 0 && <div className="skeleton-lines">{Array.from({ length: lines }).map((_, index) => <span key={index} />)}</div>}
      {cards > 0 && <div className="skeleton-cards">{Array.from({ length: cards }).map((_, index) => <span key={index} />)}</div>}
    </section>
  );
}

function mergeSession(list: NonNullable<Session>[], session: NonNullable<Session>) {
  const map = new Map(list.map((item) => [item.id, item]));
  map.set(session.id, session);
  return [...map.values()].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 6);
}

function RecentSessions({ sessions, demos }: { sessions: NonNullable<Session>[]; demos: Demo[] }) {
  return (
    <Section title="Recent sessions" className="recent-section">
      <div className="recent-list">
        {sessions.filter(wasOnBoard).length ? sessions.filter(wasOnBoard).slice(0, 4).map((session) => {
          const demo = demos.find((item) => item.id === session.demo_id);
          return <div className="recent-row" key={session.id}><span className={`signal ${recentTone(session)}`} /><strong>{demo?.name || titleCase(session.demo_id)}</strong><small>{recentStatus(session)}{session.ended_at ? ` · ended ${new Date(session.ended_at).toLocaleTimeString()}` : ''}</small></div>;
        }) : <div className="empty compact">No recent board sessions.</div>}
      </div>
    </Section>
  );
}

function wasOnBoard(session: NonNullable<Session>) {
  return Boolean(session.started_at)
    || ['starting', 'active', 'ending'].includes(session.status)
    || ['fpga_fault', 'board_offline', 'programming_failed'].includes(session.end_reason || '');
}

function recentStatus(session: NonNullable<Session>) {
  if (session.status === 'ended') return session.end_reason ? titleCase(session.end_reason) : 'Ended';
  return sessionLabel(session);
}

function recentTone(session: NonNullable<Session>): 'ok' | 'warn' | 'bad' | 'neutral' | 'info' {
  if (session.status !== 'ended') return sessionTone(session.status);
  if (session.end_reason === 'expired' || session.end_reason === 'user_ended') return 'neutral';
  if (session.end_reason === 'cancelled') return 'warn';
  return 'bad';
}

function Section({ title, className = '', children }: { title: string; className?: string; children: React.ReactNode }) {
  return <section className={`section ${className}`.trim()}><h2>{title}</h2>{children}</section>;
}

function Pill({ tone, children }: { tone: 'ok' | 'warn' | 'bad' | 'neutral' | 'info'; children: React.ReactNode }) {
  return <span className={`pill ${tone}`}><span />{children}</span>;
}

function InfoRow({ tone, label, value }: { tone: 'ok' | 'warn' | 'bad' | 'neutral' | 'info'; label: string; value: string }) {
  return <div className="info-row"><span className={`signal ${tone}`} /><strong>{label}</strong><p>{value}</p></div>;
}

function formatTemp(board: Board) {
  const temp = board?.telemetry?.temperature_c;
  return typeof temp === 'number' ? `${temp.toFixed(1)} °C` : 'Temperature unavailable';
}

function runningDemoLabel(session: NonNullable<Session> | null, demo?: Demo) {
  if (session?.status === 'active' || session?.status === 'starting') return demo?.name || titleCase(session.demo_id);
  return 'No demo running';
}

function healthSummary(tone: string, faults: Array<{ type?: string; message?: string }>) {
  if (tone === 'ok') return 'No faults reported';
  if (!faults.length) return 'Board unavailable';
  return faults.map((fault) => titleCase(fault.message || fault.type || 'Fault')).join(', ');
}

function sessionLabel(session: NonNullable<Session> | null) {
  if (!session) return 'Ready';
  if (session.status === 'queued') return 'Waiting';
  if (session.status === 'starting') return 'Starting';
  if (session.status === 'active') return 'Active';
  if (session.status === 'ending') return 'Ending';
  return 'Ready';
}

function sessionTone(status?: string): 'ok' | 'warn' | 'bad' | 'neutral' | 'info' {
  if (status === 'active') return 'ok';
  if (status === 'starting') return 'info';
  if (status === 'queued' || status === 'ending') return 'warn';
  return 'neutral';
}

function sessionCopy(session: NonNullable<Session> | null, activeTimeLeft: number | null, queueEta: number | null) {
  if (!session) return 'Pick a demo above to request the board.';
  if (session.status === 'queued') return queueEta == null ? 'You are waiting for the active demo timer.' : `Your estimated start is in ${duration(queueEta)}.`;
  if (session.status === 'starting') return 'The board is being programmed for your demo.';
  if (session.status === 'active') return activeTimeLeft == null ? 'Your demo is active with no queue pressure.' : `Your demo is active with ${duration(activeTimeLeft)} remaining.`;
  if (session.status === 'ending') return 'The board is resetting for the next user.';
  return 'Pick a demo above to request the board.';
}

createRoot(document.getElementById('root')!).render(<App />);
