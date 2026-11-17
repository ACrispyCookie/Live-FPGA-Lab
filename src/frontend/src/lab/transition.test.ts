import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reduce } from './reducer.ts';
import { changesLayout } from './transition.ts';
import type { Board, LabState, Session } from './types.ts';

const T0 = 1_700_000_000_000;
const demos = [{ id: 'gpgpu-nbody', name: 'GPGPU n-body simulator' }];
const board = (over: Partial<NonNullable<Board>> = {}): Board => ({ device_name: 'xc7z020', status: 'idle', mode: 'demo', telemetry: { temperature_c: 60 }, faults: [], ...over });
const mine = (over: Partial<Session> = {}): Session => ({ id: 's1', demo_id: 'gpgpu-nbody', status: 'queued', created_at: new Date(T0).toISOString(), ...over });
function ready(over: Partial<LabState> = {}, b: Board = board()): LabState {
  const s = reduce(initialState, { type: 'state.initial', board: b, demos, queue: { length: 0, position: null }, session: null, recent_sessions: [] }, T0);
  return { ...s, ...over };
}

test('pressing Start moves the session panel to the front', () => {
  assert.equal(changesLayout(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r' }, T0), true);
});

test('a queued turn starting keeps the session panel where it is', () => {
  const queued = ready({ session: mine({ status: 'queued' }) }, board({ status: 'running' }));
  assert.equal(changesLayout(queued, { type: 'session.updated', session: mine({ status: 'starting' }) }, T0), false);
});

test('going live with a demo URL grows the panel into the stage', () => {
  const starting = ready({ session: mine({ status: 'starting' }) }, board({ status: 'programming' }));
  assert.equal(changesLayout(starting, { type: 'session.updated', session: mine({ status: 'active', demo_url: '/d' }) }, T0), true);
});

test('a temperature reading changes nothing', () => {
  assert.equal(changesLayout(ready(), { type: 'board.updated', board: board({ telemetry: { temperature_c: 61 } }) }, T0), false);
});
