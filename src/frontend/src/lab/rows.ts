// Which button each demo card shows, from the whole state. Pure, so it is testable without React. The button says
// everything: the session panel explains why the board is unavailable, so the cards don't repeat it.
import { copy } from './copy.ts';
import { phase } from './derive.ts';
import { isLive } from './reducer.ts';
import type { Demo, LabState } from './types.ts';

export type RowState = 'start' | 'starting' | 'queued' | 'running' | 'busy' | 'blocked';

export function rowState(state: LabState, demo: Demo): { kind: RowState } {
  const p = phase(state);
  if (p === 'connecting' || p === 'offline' || p === 'fault') return { kind: 'blocked' };
  if (state.requesting?.demoId === demo.id) return { kind: 'starting' };
  const own = isLive(state.session) ? state.session : null;
  if (own && own.demo_id === demo.id) return { kind: own.status === 'queued' ? 'queued' : own.status === 'starting' ? 'starting' : 'running' };
  if (p === 'project' || own || state.requesting) return { kind: 'blocked' };
  if (p === 'busy') return { kind: 'busy' };
  return { kind: 'start' };
}

export function buttonLabel(kind: RowState): string {
  switch (kind) {
    case 'starting': return copy.demos.starting;
    case 'queued': return copy.demos.inQueue;
    case 'running': return copy.demos.running;
    case 'busy': return copy.demos.join;
    default: return copy.demos.start;
  }
}
