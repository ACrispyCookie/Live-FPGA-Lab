// Which button each demo row shows, and why, from the whole state. Pure, so it is testable without React.
import { copy } from './copy.ts';
import { phase, reservedFor } from './derive.ts';
import { isLive } from './reducer.ts';
import type { Demo, LabState } from './types.ts';

export type RowState = 'start' | 'starting' | 'queued' | 'running' | 'busy' | 'blocked';

export function rowState(state: LabState, demo: Demo): { kind: RowState; note: string | null } {
  const p = phase(state);
  if (p === 'connecting' || p === 'offline') return { kind: 'blocked', note: copy.demos.note.unavailable };
  if (p === 'fault') return { kind: 'blocked', note: copy.demos.note.fault };
  if (state.requesting?.demoId === demo.id) return { kind: 'starting', note: null };
  const own = isLive(state.session) ? state.session : null;
  if (own && own.demo_id === demo.id) return { kind: own.status === 'queued' ? 'queued' : own.status === 'starting' ? 'starting' : 'running', note: null };
  if (p === 'project') return { kind: 'blocked', note: copy.demos.note.reserved(reservedFor(state)) };
  if (own || state.requesting) return { kind: 'blocked', note: copy.demos.note.oneAtATime };
  if (p === 'busy') return { kind: 'busy', note: copy.demos.note.joins };
  return { kind: 'start', note: null };
}
