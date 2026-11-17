// The active demo: the demo's own page in a frame that takes the hero slot at full width, with a slim bar above it
// (demo name, time left when someone is waiting, Fullscreen, Open in a new tab, End session).
import { useRef, useState } from 'react';
import { copy } from '../lab/copy.ts';
import { duration, isInteractive } from '../lab/derive.ts';
import type { Session } from '../lab/types.ts';
import { Led } from './Led.tsx';

export function Stage({ session, demoName, timeLeft, onEnd }: { session: Session; demoName: string; timeLeft: number | null; onEnd: () => void }) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const c = copy.session.active;
  const url = session.demo_url || 'about:blank';
  return (
    <div className="stage" id="stage" data-kind={isInteractive(session.demo_id) ? 'interactive' : 'video'}>
      <div className="sbar" data-pad>
        <span className="who"><Led on />{demoName}</span>
        {timeLeft != null && <span className="left">{c.left(duration(timeLeft))}</span>}
        <div className="acts">
          <button type="button" className="btn s" onClick={() => frameRef.current?.requestFullscreen?.()}>{c.fullscreen}</button>
          <button type="button" className="btn s" onClick={() => window.open(url, '_blank', 'noopener,noreferrer')}>{c.newTab}</button>
          <button type="button" className="btn s p" onClick={onEnd}>{c.end}</button>
        </div>
      </div>
      <div className="frame">
        <iframe ref={frameRef} title={`${demoName} demo`} src={url} allow="fullscreen" onLoad={() => setLoaded(true)} />
        {!loaded && <div className="loading">{c.loading}</div>}
      </div>
    </div>
  );
}
