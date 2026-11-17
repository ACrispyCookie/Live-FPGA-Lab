// The visitor's own panel: the single place that says what is happening to them, in one headline and one sentence.
import { copy } from '../lab/copy.ts';
import type { Ref } from 'react';
import { demoName, duration, endedSentence, phase, progressSteps, queueEta, queueSentence, reservedFor, runningSession, boardStatus } from '../lab/derive.ts';
import type { LabState } from '../lab/types.ts';
import { DemoThumb } from './DemoList.tsx';
import { Skel } from './Skeleton.tsx';
import { Steps } from './Steps.tsx';

export type SessionHandlers = { onCancel: () => void; onEnd: () => void; onRetry: (demoId: string) => void };
type PanelProps = { state: LabState; lead?: boolean; arrival: string | null; headingRef?: Ref<HTMLHeadingElement>; flash?: boolean; onFlashEnd?: () => void } & SessionHandlers;

export function SessionPanel({ state, lead = false, arrival, onCancel, onEnd, onRetry, headingRef, flash = false, onFlashEnd }: PanelProps) {
  const p = phase(state);
  const c = copy.session;
  const demoId = state.requesting?.demoId ?? state.session?.demo_id ?? state.lastEnded?.demo_id ?? '';
  const demo = demoId ? demoName(state.demos, demoId) : '';
  const steps = progressSteps(state);
  let body: React.ReactNode;
  let live = '';
  let warn = false;

  if (steps) {
    // the request in flight: which demo, where it stands, and one sentence on what happens now
    const failed = steps.some((s) => s.state === 'failed');
    const now = failed ? `${c.failed.head(demo)}. ${c.failed.body}`
      : p === 'requesting' ? `${arrival ? `${arrival}. ` : ''}${c.requesting.body}`
      : p === 'starting' ? `${arrival ? `${arrival}. ` : ''}${c.starting.body}`
      : c.opening;
    live = failed ? c.failed.head(demo) : steps.find((s) => s.state === 'current')?.label ?? '';
    body = <>
      <div className="pick">
        <span className="pthumb"><DemoThumb demo={state.demos.find((d) => d.id === demoId) ?? { id: demoId, name: demo }} /></span>
        <b>{demo}</b>
      </div>
      <Steps steps={steps} />
      <p className="now">{now}</p>
      {p === 'starting' && <div className="row"><button type="button" className="btn" onClick={onCancel}>{c.starting.cancel}</button></div>}
      {failed && <div className="row"><button type="button" className="btn live" onClick={() => onRetry(demoId)}>{c.failed.retry}</button><a className="btn" href="#demos">{c.busy.cta}</a></div>}
    </>;
  } else switch (p) {
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

  if (!live && p === 'queued') live = queueSentence(state.queue);
  return (
    <div className={`session${warn ? ' warn' : ''}${flash ? ' flash' : ''}`} data-pad={lead || undefined} onAnimationEnd={(e) => { if (e.animationName === 'ring') onFlashEnd?.(); }}>
      <h2 ref={headingRef} tabIndex={-1}>{c.heading}</h2>
      <p className="sr" aria-live="polite">{live}</p>
      <div className="phase" key={p}>{body}</div>
      {state.lastError && <p className="error">{state.lastError}</p>}
    </div>
  );
}
