// The active demo: the demo's own page in a frame that takes the visitor's slot at full width, with a slim bar above it
// (demo name, time left when someone is waiting, Fullscreen, Open in a new tab, End session). Until the page has
// loaded, the progress card the visitor was following covers it with Live as the current step; once it loads, Live
// lights, the finished track holds for a moment, and the card fades away.
import { useEffect, useRef, useState } from 'react';
import { copy } from '../lab/copy.ts';
import { duration, isInteractive, stageSteps } from '../lab/derive.ts';
import type { LabState, Session } from '../lab/types.ts';
import { DemoThumb } from './DemoList.tsx';
import { Led } from './Led.tsx';
import { Steps } from './Steps.tsx';

const HOLD_MS = 500;

export function Stage({ state, session, demoName, timeLeft, onEnd }: { state: LabState; session: Session; demoName: string; timeLeft: number | null; onEnd: () => void }) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [fading, setFading] = useState(false);
  const [covered, setCovered] = useState(true);
  const c = copy.session.active;
  const url = session.demo_url || 'about:blank';
  const demo = state.demos.find((d) => d.id === session.demo_id) ?? { id: session.demo_id, name: demoName };

  const loadedRef = useRef(false);
  function onLoad() {
    if (loadedRef.current) return;
    loadedRef.current = true;
    setLoaded(true);
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) setCovered(false);
    else window.setTimeout(() => setFading(true), HOLD_MS);
  }

  // A blank frame (no demo page) has loaded before React can listen; a real page reports through onLoad, with a native
  // listener as a backup.
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    if (url === 'about:blank') { onLoad(); return; }
    frame.addEventListener('load', onLoad);
    return () => frame.removeEventListener('load', onLoad);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

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
        <iframe ref={frameRef} title={`${demoName} demo`} src={url} allow="fullscreen" onLoad={onLoad} />
        {covered && (
          <div className={`cover${fading ? ' out' : ''}`} onTransitionEnd={(e) => { if (e.target === e.currentTarget) setCovered(false); }}>
            <div className="progress">
              <div className="pick"><span className="pthumb"><DemoThumb demo={demo} /></span><b>{demoName}</b></div>
              <Steps steps={stageSteps(state, loaded)} />
              <p className="now">{c.opening}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
