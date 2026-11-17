// The visitor's own panel: the single place that says what is happening to them, in one headline and one sentence.
import { copy } from '../lab/copy.ts';
import { demoName, duration, endedSentence, phase, queueEta, queueSentence, reservedFor, runningSession, boardStatus } from '../lab/derive.ts';
import type { LabState } from '../lab/types.ts';
import { Led } from './Led.tsx';
import { Skel } from './Skeleton.tsx';

export type SessionHandlers = { onCancel: () => void; onEnd: () => void };

export function SessionPanel({ state, arrival, onCancel, onEnd }: { state: LabState; arrival: string | null } & SessionHandlers) {
  const p = phase(state);
  const c = copy.session;
  const demo = state.requesting ? demoName(state.demos, state.requesting.demoId)
    : state.session ? demoName(state.demos, state.session.demo_id)
    : state.lastEnded ? demoName(state.demos, state.lastEnded.demo_id) : '';
  let body: React.ReactNode;
  let warn = false;

  switch (p) {
    case 'connecting':
      body = <><Skel h={38} w="62%" pill /><Skel h={16} w="90%" pill /><Skel h={16} w="70%" pill /><Skel h={44} w={160} pill /></>;
      break;
    case 'offline':
      body = <><p className="big">{c.offline.head}</p><p className="sub">{c.offline.body}</p></>;
      break;
    case 'fault':
      warn = true;
      body = <><p className="demo-name">{c.fault.head(boardStatus(state).detail)}</p><p className="sub">{c.fault.body}</p></>;
      break;
    case 'project': {
      const what = reservedFor(state);
      body = <><p className="big">{c.project.head(what)}</p><p className="sub">{c.project.body(what)}</p></>;
      break;
    }
    case 'idle':
      body = <><p className="big">{c.idle.head}</p><p className="sub">{c.idle.body}</p><a className="btn live" href="#demos">{c.idle.cta}</a></>;
      break;
    case 'busy': {
      const run = runningSession(state);
      body = <><p className="big">{c.busy.head}</p><p className="sub">{c.busy.body(run ? demoName(state.demos, run.demo_id) : null, state.queue.length)}</p><a className="btn live" href="#demos">{c.busy.cta}</a></>;
      break;
    }
    case 'requesting':
      body = <><p className="pulseline"><Led on blink /><span className="demo-name">{c.requesting.head(demo)}</span></p><p className="sub">{arrival ? `${arrival}. ` : ''}{c.requesting.body}</p></>;
      break;
    case 'queued': {
      const eta = queueEta(state.queue, state.now);
      const position = state.queue.position || 1;
      const pct = eta == null ? 0 : Math.max(0, Math.min(100, 100 - (eta / (position * 300)) * 100));
      body = <>
        <p className="big"><em>{queueSentence(state.queue).split(' ')[0]}</em> {queueSentence(state.queue).split(' ').slice(1).join(' ')}</p>
        <p className="sub">{c.queued.forDemo} <span className="demo-name">{demo}</span></p>
        <p className="sub">{eta == null ? c.queued.noEta : c.queued.eta(duration(eta))}</p>
        <div className="bar" style={{ '--w': `${pct}%` } as React.CSSProperties}><i /></div>
        <div className="row"><button type="button" className="btn" onClick={onCancel}>{c.queued.leave}</button></div>
      </>;
      break;
    }
    case 'starting':
      body = <><p className="pulseline"><Led on blink /><span className="demo-name">{c.starting.head(demo)}</span></p><p className="sub">{arrival ? `${arrival}. ` : ''}{c.starting.body}</p><div className="row"><button type="button" className="btn" onClick={onCancel}>{c.starting.cancel}</button></div></>;
      break;
    case 'active':
      body = <><p className="big">{copy.pill.running}</p><p className="sub"><span className="demo-name">{demo}</span></p><div className="row"><button type="button" className="btn p" onClick={onEnd}>{c.active.end}</button></div></>;
      break;
    case 'ending':
      body = <><p className="big">{c.ending.head}</p><p className="sub">{c.ending.body}</p></>;
      break;
    case 'ended':
      body = <><p className="big">{copy.recent.outcome.ended}</p><p className="sub">{endedSentence(state.lastEnded!, demo, reservedFor(state))}</p><a className="btn live" href="#demos">{c.ended.again}</a></>;
      break;
  }

  return (
    <div className={`session${warn ? ' warn' : ''}`} aria-live="polite">
      <h2>{c.heading}</h2>
      <div className="phase" key={p}>{body}</div>
      {state.lastError && <p className="error">{state.lastError}</p>}
    </div>
  );
}
