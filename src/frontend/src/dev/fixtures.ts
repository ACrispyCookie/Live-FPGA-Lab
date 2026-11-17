// Example states for ?mock=<name>, enabled only in builds made with VITE_MOCK_STATES=1. They feed the same
// reducer the socket feeds, so every component renders exactly as it would with live data.
import { initialState, reduce } from '../lab/reducer.ts';
import type { Board, LabState, Session } from '../lab/types.ts';

const NOW = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();

const DEMOS = [
  ['gpgpu-nbody', 'GPGPU n-body simulator', 'Interactive n-body simulation running on the FPGA.'],
  ['dvd-logo-video', 'DVD Logo HDMI', 'Live HDMI output captured directly from the FPGA.'],
  ['gpgpu-ripple', 'GPGPU ripple animation', 'The GPGPU renders an animated ripple frame after frame, shown live over HDMI.'],
  ['gpgpu-triangle', 'GPGPU triangle', 'The GPGPU rasterizes one triangle into the framebuffer, shown live over HDMI.'],
  ['gpgpu-metaballs', 'GPGPU metaballs', 'Glowing blobs drift across the screen, merging and splitting; the GPGPU renders every frame, shown live over HDMI.'],
  ['gpgpu-julia', 'GPGPU Julia set', 'An animated Julia set morphs frame after frame as the GPGPU renders it, shown live over HDMI.'],
  ['gpgpu-cube', 'GPGPU spinning cube', 'The GPGPU rasterizes a flat-shaded cube spinning in perspective, shown live over HDMI.'],
  ['gpgpu-mandelbrot', 'GPGPU Mandelbrot zoom', 'An endless zoom into the Mandelbrot set, rendered by the GPGPU frame after frame, shown live over HDMI.'],
].map(([id, name, description]) => ({ id, name, description, thumbnail_url: `/api/demos/${id}/thumbnail` }));

const board = (over: Partial<NonNullable<Board>> = {}): Board => ({
  device_name: 'xc7z020', label: 'Smart Zynq SL', status: 'idle', mode: 'demo', reserved_for: 'GPGPU testing',
  telemetry: { temperature_c: 61.9 }, faults: [], ...over,
});

const session = (over: Partial<Session> = {}): Session => ({ id: 'mine', demo_id: 'gpgpu-nbody', status: 'queued', created_at: iso(NOW - 20_000), ...over });
const other = (demo_id: string, status: 'active' | 'starting' = 'active'): Session => ({ id: 'other', demo_id, status, created_at: iso(NOW - 120_000), started_at: iso(NOW - 100_000) });
const RECENT: Session[] = [
  { id: 'r1', demo_id: 'gpgpu-nbody', status: 'ended', created_at: iso(NOW - 3_600_000), started_at: iso(NOW - 3_590_000), ended_at: iso(NOW - 3_300_000), end_reason: 'user_ended' },
  { id: 'r2', demo_id: 'gpgpu-metaballs', status: 'ended', created_at: iso(NOW - 5_000_000), started_at: iso(NOW - 4_990_000), ended_at: iso(NOW - 4_690_000), end_reason: 'expired' },
  { id: 'r3', demo_id: 'dvd-logo-video', status: 'ended', created_at: iso(NOW - 6_000_000), started_at: iso(NOW - 5_990_000), ended_at: iso(NOW - 5_800_000), end_reason: 'user_ended' },
  { id: 'r4', demo_id: 'gpgpu-cube', status: 'ended', created_at: iso(NOW - 90_000_000), started_at: iso(NOW - 89_990_000), ended_at: iso(NOW - 89_980_000), end_reason: 'programming_failed' },
];
const TEMPS = [61.2, 61.4, 61.9, 62.3, 62.1, 61.8, 62.6, 63.1, 63.4, 63.0, 62.4, 62.2, 61.9, 61.9];

function make(b: Board, over: { session?: Session | null; recent?: Session[]; queue?: LabState['queue'] } = {}, patch: Partial<LabState> = {}): LabState {
  let s = reduce(initialState, { type: 'socket.opened' }, NOW - 60_000);
  s = reduce(s, { type: 'state.initial', board: b, demos: DEMOS, queue: over.queue ?? { length: 0, position: null }, session: over.session ?? null, recent_sessions: [...(over.recent ?? []), ...RECENT] }, NOW - 60_000);
  TEMPS.forEach((c, i) => { s = reduce(s, { type: 'board.updated', board: { ...b, telemetry: { temperature_c: c } } }, NOW - (TEMPS.length - i) * 4000); });
  s = reduce(s, { type: 'board.updated', board: b }, NOW - 2000);
  s = reduce(s, { type: 'tick', now: NOW }, NOW);
  return { ...s, ...patch };
}

export const FIXTURES: Record<string, () => LabState> = {
  connecting: () => ({ ...initialState, socket: 'connecting' }),
  idle: () => make(board()),
  busy: () => make(board({ status: 'running' }), { recent: [other('gpgpu-cube')], queue: { length: 1, position: null, active_expires_at: iso(NOW + 200_000) } }),
  arrival: () => make(board(), {}, { requesting: { demoId: 'gpgpu-nbody', requestId: 'mock' } }),
  requesting: () => make(board(), {}, { requesting: { demoId: 'gpgpu-julia', requestId: 'mock' } }),
  queued: () => make(board({ status: 'running' }), { session: session({ status: 'queued' }), recent: [other('gpgpu-metaballs')], queue: { length: 3, position: 2, active_expires_at: iso(NOW + 90_000) } }),
  starting: () => make(board({ status: 'programming' }), { session: session({ status: 'starting', demo_id: 'gpgpu-julia' }) }),
  active: () => make(board({ status: 'running' }), { session: session({ status: 'active', started_at: iso(NOW - 48_000), expires_at: iso(NOW + 252_000), demo_url: 'about:blank' }), queue: { length: 1, position: null, active_expires_at: iso(NOW + 252_000) } }),
  ending: () => make(board({ status: 'running' }), { session: session({ status: 'ending', started_at: iso(NOW - 248_000), end_reason: 'user_ended' }) }),
  ended: () => make(board(), {}, { lastEnded: session({ status: 'ended', started_at: iso(NOW - 300_000), ended_at: iso(NOW - 5000), end_reason: 'expired' }) }),
  project: () => make(board({ mode: 'project' })),
  fault: () => make(board({ status: 'fault', faults: [{ type: 'over_temperature', message: 'Over temperature' }], telemetry: { temperature_c: 71.3 } })),
  offline: () => make(board({ status: 'offline', telemetry: { temperature_c: null } })),
  reconnecting: () => ({ ...make(board({ status: 'running' }), { session: session({ status: 'active', demo_url: 'about:blank' }) }), socket: 'reconnecting' }),
  longname: () => ({ ...make(board()), demos: [...DEMOS, { id: 'gpgpu-cathedral', name: 'GPGPU deferred-shading cathedral flythrough with volumetric fog', description: 'A slow camera path through a cathedral nave, lit by shafts of light through volumetric fog; the GPGPU shades every pixel of every frame, shown live over HDMI.', thumbnail_url: null }] }),
  failed: () => make(board(), {}, { lastEnded: session({ status: 'ended', demo_id: 'gpgpu-cube', started_at: null, ended_at: iso(NOW - 4000), end_reason: 'programming_failed' }) }),
  error: () => make(board(), {}, { lastError: 'The FPGA is currently reserved for owner projects.' }),
};

/** The fixture named by ?mock=, or null when the switch is off or the name is unknown. */
export function mockState(): LabState | null {
  if (import.meta.env.VITE_MOCK_STATES !== '1') return null;
  const name = new URLSearchParams(location.search).get('mock');
  const build = name ? FIXTURES[name] : undefined;
  return build ? build() : null;
}
