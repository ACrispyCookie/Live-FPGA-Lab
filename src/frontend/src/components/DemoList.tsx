// The demos as thumbnail rows. Each row's button says exactly what pressing it does, or why it can't.
import { copy } from '../lab/copy.ts';
import { demoKind } from '../lab/derive.ts';
import { rowState, type RowState } from '../lab/rows.ts';
import type { Demo, LabState } from '../lab/types.ts';
import { Skel } from './Skeleton.tsx';

function DemoThumb({ demo }: { demo: Demo }) {
  if (demo.thumbnail_url) return <img src={demo.thumbnail_url} alt="" width="120" height="76" loading="lazy" />;
  return (
    <svg viewBox="0 0 120 76" aria-hidden="true">
      <rect width="120" height="76" fill="#183539" />
      <path d="M0 38 H52" stroke="#3b7a82" strokeWidth="3" strokeLinecap="round" />
      <circle cx="60" cy="38" r="7" fill="#41e2f2" />
    </svg>
  );
}

function label(kind: RowState): string {
  switch (kind) {
    case 'starting': return copy.demos.starting;
    case 'queued': return copy.demos.inQueue;
    case 'running': return copy.demos.running;
    default: return copy.demos.start;
  }
}

export function DemoRow({ demo, state, onStart }: { demo: Demo; state: LabState; onStart: (demoId: string) => void }) {
  const { kind, note } = rowState(state, demo);
  const live = kind === 'start' || kind === 'busy';
  const chosen = kind === 'starting' || kind === 'queued' || kind === 'running';
  return (
    <article className={`demo${chosen ? ' chosen' : ''}`} data-demo={demo.id}>
      <div className="in">
        <div className="thumb"><DemoThumb demo={demo} /></div>
        <div className="text">
          <h3>{demo.name}</h3>
          {demo.description && <p>{demo.description}</p>}
        </div>
        <div className="kind"><span className="tag">{demoKind(demo)}</span></div>
        <div className="act">
          <button type="button" className={`btn${live ? ' live' : ''}`} disabled={!live} onClick={() => onStart(demo.id)}>{label(kind)}</button>
          {note && <small>{note}</small>}
        </div>
      </div>
    </article>
  );
}

export function DemoList({ state, onStart }: { state: LabState; onStart: (demoId: string) => void }) {
  if (!state.ready) {
    return (
      <div className="demolist">
        {Array.from({ length: 4 }, (_, i) => (
          <article key={i} className="demo loading" aria-hidden="true">
            <div className="in">
              <div className="thumb" />
              <div className="text"><Skel h={22} w="55%" pill /><Skel h={16} w="90%" pill /></div>
              <div className="kind"><Skel h={22} w={120} pill /></div>
              <div className="act"><Skel h={40} w={84} pill /></div>
            </div>
          </article>
        ))}
      </div>
    );
  }
  if (!state.demos.length) return <div className="empty">{copy.demos.empty}</div>;
  return <div className="demolist">{state.demos.map((demo) => <DemoRow key={demo.id} demo={demo} state={state} onStart={onStart} />)}</div>;
}
