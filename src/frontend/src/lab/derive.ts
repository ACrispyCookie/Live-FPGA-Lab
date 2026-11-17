// Pure derivations: from the state to the words and numbers the components show.
import type { Board, Demo, LabState, Phase, QueueState, Session, TempSample } from './types.ts';
import { copy } from './copy.ts';
import { isLive } from './reducer.ts';

export const CONTENDED_SECONDS = 300;

export type Tone = 'dim' | 'cyan' | 'amber' | 'silk';

export function titleCase(value?: string | null): string {
  return String(value || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** What the board is used for while reserved, as configured on the server (WEB_API_RESERVED_FOR). */
export function reservedFor(state: LabState): string {
  return state.board?.reserved_for || copy.board.status.reservedDefault;
}

export function demoName(demos: Demo[], id: string): string {
  return demos.find((d) => d.id === id)?.name || titleCase(id);
}

/** The session that holds the board right now: the visitor's own, or another visitor's seen in the recent list. */
export function runningSession(state: LabState): Session | null {
  const own = state.session;
  if (isLive(own) && own.status !== 'queued') return own;
  return state.recent.find((s) => s.status === 'active' || s.status === 'starting') || null;
}

function boardFault(board: Board): boolean {
  return Boolean(board) && (board!.status === 'fault' || (board!.faults?.length ?? 0) > 0);
}

export function phase(state: LabState): Phase {
  if (!state.ready) return 'connecting';
  if (state.requesting) return 'requesting';
  const own = state.session;
  if (isLive(own)) {
    if (state.endRequested) return 'ending';
    return own.status as Phase;
  }
  const board = state.board;
  if (!board || board.status === 'offline') return 'offline';
  if (board.mode === 'project') return 'project';
  if (boardFault(board)) return 'fault';
  if (state.lastEnded) return 'ended';
  if (board.status === 'running' || runningSession(state)) return 'busy';
  return 'idle';
}

export function secondsUntil(value: string | null | undefined, now: number): number | null {
  if (!value) return null;
  const t = Date.parse(value);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((t - now) / 1000));
}

export function timeLeft(session: Session | null, now: number): number | null {
  return session ? secondsUntil(session.expires_at, now) : null;
}

export function queueEta(queue: QueueState, now: number, contendedSeconds: number = CONTENDED_SECONDS): number | null {
  if (!queue.position) return null;
  const head = secondsUntil(queue.active_expires_at, now);
  if (head == null) return null;
  return head + Math.max(0, queue.position - 1) * contendedSeconds;
}

export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

export function queueSentence(queue: QueueState): string {
  return `${ordinal(queue.position || 1)} of ${queue.length} waiting`;
}

export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(s / 60);
  const rest = s % 60;
  return minutes ? `${minutes}m ${String(rest).padStart(2, '0')}s` : `${rest}s`;
}

export function readAgo(temps: TempSample[], now: number): number | null {
  if (!temps.length) return null;
  return Math.max(0, Math.round((now - temps[temps.length - 1].at) / 1000));
}

const num = (x: number) => String(Number(x.toFixed(1)));

export function sparkPath(temps: TempSample[], width: number, height: number): string {
  if (temps.length < 2) return '';
  const pad = 4;
  const values = temps.map((t) => t.c);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;
  return temps
    .map((t, i) => {
      const x = (i / (temps.length - 1)) * width;
      const y = range === 0 ? height / 2 : height - pad - ((t.c - min) / range) * (height - 2 * pad);
      return `${i ? 'L' : 'M'}${num(x)} ${num(y)}`;
    })
    .join(' ');
}

export function demoKind(demo: Demo): string {
  return demo.id === 'gpgpu-nbody' ? copy.demos.kind.interactive : copy.demos.kind.hdmi;
}

export function recentOutcome(session: Session, reserved: string = copy.board.status.reservedDefault): { text: string; tone: 'ok' | 'neutral' | 'bad' } {
  if (session.status !== 'ended') {
    return { text: copy.recent.outcome[session.status] || titleCase(session.status), tone: session.status === 'active' ? 'ok' : 'neutral' };
  }
  const reason = session.end_reason || 'ended';
  const text = reason === 'board_reserved' ? copy.recent.reserved(reserved) : copy.recent.outcome[reason] || titleCase(reason);
  const tone = reason === 'user_ended' ? 'ok'
    : ['programming_failed', 'fpga_fault', 'board_offline'].includes(reason) ? 'bad'
    : 'neutral';
  return { text, tone };
}

export function endedSentence(session: Session, demoNameText: string, reserved: string = copy.board.status.reservedDefault): string {
  if (session.end_reason === 'board_reserved') return copy.endedReserved(demoNameText, reserved);
  const make = copy.endedSentence[session.end_reason || ''] || copy.endedSentence.default;
  return make(demoNameText);
}

export function boardStatus(state: LabState): { word: string; tone: Tone; detail: string } {
  const b = state.board;
  const c = copy.board.status;
  if (!b || b.status === 'offline') return { word: c.offline, tone: 'dim', detail: c.offlineDetail };
  if (b.mode === 'project') return { word: c.reserved, tone: 'cyan', detail: c.reservedDetail(reservedFor(state)) };
  if (boardFault(b)) {
    const fault = b.faults?.[0];
    return { word: c.fault, tone: 'amber', detail: fault?.message || (fault?.type ? titleCase(fault.type) : c.faultDetail) };
  }
  const run = runningSession(state);
  if (run) {
    const mine = state.session?.id === run.id;
    const word = run.status === 'starting' ? c.programming : run.status === 'ending' ? c.resetting : c.running;
    return { word, tone: 'cyan', detail: `${demoName(state.demos, run.demo_id)}, ${mine ? c.yourSession : c.anotherVisitor}` };
  }
  if (b.status === 'running') return { word: c.running, tone: 'cyan', detail: c.anotherVisitorOnly };
  if (b.status && b.status !== 'idle') return { word: titleCase(b.status), tone: 'cyan', detail: c.idleDetail };
  return { word: c.idle, tone: 'silk', detail: c.idleDetail };
}

export function pillText(state: LabState, sessionVisible: boolean): { text: string; tone: 'dim' | 'cyan' | 'amber' } {
  if (!state.ready) return { text: copy.pill.connecting, tone: 'dim' };
  if (state.socket !== 'connected') return { text: copy.pill.reconnecting, tone: 'amber' };
  const p = phase(state);
  if (!sessionVisible) {
    switch (p) {
      case 'requesting': return { text: copy.pill.starting, tone: 'cyan' };
      case 'queued': {
        const eta = queueEta(state.queue, state.now);
        return { text: copy.pill.inLine(ordinal(state.queue.position || 1), eta == null ? null : duration(eta)), tone: 'cyan' };
      }
      case 'starting': return { text: copy.pill.programming, tone: 'cyan' };
      case 'active': {
        const left = timeLeft(state.session, state.now);
        return { text: left == null ? copy.pill.running : copy.pill.runningLeft(duration(left)), tone: 'cyan' };
      }
      case 'ending': return { text: copy.pill.ending, tone: 'cyan' };
    }
  }
  if (p === 'project') return { text: copy.pill.reserved(reservedFor(state)), tone: 'cyan' };
  const bs = boardStatus(state);
  return { text: bs.word, tone: bs.tone === 'silk' ? 'dim' : bs.tone };
}
