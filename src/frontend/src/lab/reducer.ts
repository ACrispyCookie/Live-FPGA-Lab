// One pure reducer turns server events and local actions into the lab's state. No timers, no sockets, no DOM.
import type { Action, Board, LabState, Session, TempSample, Toast, ToastLevel } from './types.ts';
import { copy } from './copy.ts';

export const TEMP_WINDOW_MS = 300_000;
export const TEMP_MAX_SAMPLES = 200;
export const RECENT_MAX = 6;
export const TOASTS_MAX = 4;

export const initialState: LabState = {
  socket: 'connecting',
  ready: false,
  now: 0,
  board: null,
  demos: [],
  queue: { length: 0, position: null, active_expires_at: null },
  session: null,
  recent: [],
  requesting: null,
  endRequested: false,
  lastError: null,
  lastEnded: null,
  temps: [],
  toasts: [],
};

export function isLive(session: Session | null | undefined): session is Session {
  return Boolean(session) && session!.status !== 'ended';
}

function addSample(temps: TempSample[], board: Board, now: number): TempSample[] {
  const c = board?.telemetry?.temperature_c;
  if (typeof c !== 'number' || !Number.isFinite(c)) return temps;
  const cutoff = now - TEMP_WINDOW_MS;
  return [...temps.filter((t) => t.at >= cutoff), { at: now, c }].slice(-TEMP_MAX_SAMPLES);
}

function sortRecent(list: Session[]): Session[] {
  return [...list].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, RECENT_MAX);
}

function mergeRecent(list: Session[], session: Session): Session[] {
  const map = new Map(list.map((item) => [item.id, item]));
  map.set(session.id, session);
  return sortRecent([...map.values()]);
}

function toastLevel(value: unknown): ToastLevel {
  if (value === 'success' || value === 'warn' || value === 'error' || value === 'info') return value;
  if (value === 'warning') return 'warn';
  return 'info';
}

export function reduce(state: LabState, action: Action, now: number = Date.now()): LabState {
  switch (action.type) {
    case 'state.initial': {
      const session = action.session ?? null;
      return {
        ...state,
        socket: 'connected', // the initial state only ever arrives over an open socket
        now,
        ready: true,
        board: action.board ?? null,
        demos: action.demos ?? [],
        queue: action.queue ?? { length: 0, position: null, active_expires_at: null },
        session: isLive(session) ? session : null,
        lastEnded: session && !isLive(session) ? session : state.lastEnded,
        recent: sortRecent(action.recent_sessions ?? []),
        temps: addSample([], action.board ?? null, now),
        requesting: null,
        endRequested: false,
      };
    }
    case 'board.updated':
      return { ...state, board: action.board ?? null, temps: addSample(state.temps, action.board ?? null, now) };
    case 'queue.updated':
      return { ...state, queue: action.queue ?? { length: 0, position: null, active_expires_at: null } };
    case 'recent_sessions.updated':
      return { ...state, recent: sortRecent(action.sessions ?? []) };
    case 'session.updated': {
      const session = action.session;
      if (!session) return { ...state, session: null, requesting: null, endRequested: false };
      if (session.status === 'ended') {
        const mine = !state.session || state.session.id === session.id;
        return {
          ...state,
          session: mine ? null : state.session,
          lastEnded: mine ? session : state.lastEnded,
          recent: mergeRecent(state.recent, session),
          requesting: null,
          endRequested: false,
        };
      }
      return {
        ...state,
        session,
        requesting: null,
        lastError: null,
        lastEnded: null,
        endRequested: session.status === 'ending' ? false : state.endRequested,
        recent: mergeRecent(state.recent, session),
      };
    }
    case 'command.result': {
      if (!state.requesting || action.request_id !== state.requesting.requestId) return state;
      if (action.ok) return { ...state, requesting: null };
      return { ...state, requesting: null, lastError: action.error?.message || copy.session.errorFallback };
    }
    case 'ui.message': {
      // the session panel already narrates the visitor's own progress; only warnings and errors interrupt
      const level = toastLevel(action.level);
      if (level === 'info' || level === 'success') return state;
      const toast: Toast = { id: `${now}-${Math.random().toString(36).slice(2, 8)}`, level, message: String(action.message || copy.toast.fallback) };
      return { ...state, toasts: [...state.toasts.slice(-(TOASTS_MAX - 1)), toast] };
    }
    case 'socket.opened':
      return { ...state, socket: 'connected' };
    case 'socket.closed':
      return { ...state, socket: 'reconnecting', requesting: null };
    case 'start.requested':
      if (state.requesting || isLive(state.session)) return state;
      return { ...state, requesting: { demoId: action.demoId, requestId: action.requestId }, lastError: null, lastEnded: null };
    case 'end.requested':
      if (!isLive(state.session)) return state;
      return { ...state, endRequested: true };
    case 'error.dismissed':
      return { ...state, lastError: null };
    case 'toast.dismissed':
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) };
    case 'tick':
      return { ...state, now: action.now };
    default:
      return state;
  }
}
