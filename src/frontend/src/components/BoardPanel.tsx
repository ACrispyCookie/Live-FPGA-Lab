// The component the trace lands on: the portfolio widget's cyan band, then the board's name, the one-board
// rule and three readouts with units and conditions (status, die temperature with its sparkline, queue).
import type { ReactNode } from 'react';
import { copy } from '../lab/copy.ts';
import { boardStatus, phase, readAgo, type Tone } from '../lab/derive.ts';
import type { LabState } from '../lab/types.ts';
import { Led } from './Led.tsx';
import { Skel } from './Skeleton.tsx';
import { Sparkline } from './Sparkline.tsx';

function Pins() {
  return (
    <svg className="pins" width="66" height="13" viewBox="0 0 66 13" aria-hidden="true">
      {[6.5, 24.2, 41.9, 59.6].map((cx) => <circle key={cx} cx={cx} cy="6.5" r="5.5" fill="#d8b46a" stroke="#a8873f" strokeWidth="2" />)}
    </svg>
  );
}

function Readout({ label, value, tone, detail, className = '', children }: { label: string; value: string; tone: Tone; detail: string; className?: string; children?: ReactNode }) {
  return (
    <div className={`ro tone-${tone}${className ? ` ${className}` : ''}`}>
      <small>{label}</small>
      <b>{value}</b>
      {children}
      <span className="when">{detail}</span>
    </div>
  );
}

export function BoardPanel({ state, compact = false }: { state: LabState; compact?: boolean }) {
  const p = phase(state);
  const connecting = p === 'connecting';
  const b = state.board;
  const status = boardStatus(state);
  const temp = b?.telemetry?.temperature_c;
  const hasTemp = typeof temp === 'number';
  const ago = readAgo(state.temps, state.now);
  const online = state.ready && state.socket === 'connected' && p !== 'offline';
  const waiting = state.queue.length;

  return (
    <div className={`board${compact ? ' compact' : ''}`}>
      <div className="band" data-pad>
        <span className="title"><Led on={online} blink={p === 'starting' || p === 'requesting'} ink />{copy.band}</span>
        <Pins />
      </div>
      <div className="body">
        <div className="ident">
          {connecting ? <><Skel h={38} w="46%" pill /><Skel h={16} w="38%" pill /></> : <>
            <h1>{b?.label || copy.board.fallbackName}</h1>
            <p>{copy.board.where(b?.device_name ?? null)}</p>
          </>}
        </div>
        {connecting ? <Skel h={16} w="90%" pill /> : <p className="what">{copy.board.rule}</p>}
        <div className="readouts">
          {connecting ? <><Skel className="ro" /><Skel className="ro temp" /><Skel className="ro" /></> : <>
            <Readout label={copy.board.labels.status} value={status.word} tone={status.tone} detail={status.detail} />
            <Readout className="temp" label={copy.board.labels.temperature} value={hasTemp ? `${temp.toFixed(1)} °C` : copy.board.temp.none}
              tone={hasTemp ? (status.tone === 'amber' ? 'amber' : 'silk') : 'dim'} detail={ago == null ? copy.board.temp.read : copy.board.temp.readAgo(ago)}>
              <Sparkline temps={state.temps} />
            </Readout>
            <Readout label={copy.board.labels.queue} value={waiting ? copy.board.queue.waiting(waiting) : copy.board.queue.empty} tone={waiting ? 'silk' : 'dim'}
              detail={waiting === 0 ? copy.board.queue.nobody : waiting === 1 ? copy.board.queue.one : copy.board.queue.many} />
          </>}
        </div>
      </div>
    </div>
  );
}
