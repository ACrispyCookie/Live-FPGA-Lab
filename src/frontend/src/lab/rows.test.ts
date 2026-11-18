import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reduce } from './reducer.ts';
import { buttonLabel, rowState } from './rows.ts';
import type { Board, LabState, Session } from './types.ts';

const T0 = 1_700_000_000_000;
const demos = [{ id: 'gpgpu-nbody', name: 'GPGPU n-body simulator' }, { id: 'gpgpu-cube', name: 'GPGPU spinning cube' }];
const board = (over: Partial<NonNullable<Board>> = {}): Board => ({ device_name: 'xc7z020', status: 'idle', mode: 'demo', telemetry: { temperature_c: 60 }, faults: [], ...over });
const mine = (over: Partial<Session> = {}): Session => ({ id: 's1', demo_id: 'gpgpu-nbody', status: 'active', created_at: new Date(T0).toISOString(), ...over });
function ready(b: Board = board(), over: Partial<LabState> = {}): LabState {
  const s = reduce(initialState, { type: 'state.initial', board: b, demos, queue: { length: 0, position: null }, session: null, recent_sessions: [] }, T0);
  return { ...s, ...over };
}

test('a free board offers Start on every demo', () => {
  assert.deepEqual(rowState(ready(), demos[1]), { kind: 'start' });
  assert.equal(buttonLabel('start'), 'Start');
});

test('a busy board offers to join the queue, in the button itself', () => {
  assert.deepEqual(rowState(ready(board({ status: 'running' })), demos[1]), { kind: 'busy' });
  assert.equal(buttonLabel('busy'), 'Join the queue');
});

test('with a session of your own the other demos are simply unavailable, without a note', () => {
  assert.deepEqual(rowState(ready(board({ status: 'running' }), { session: mine() }), demos[1]), { kind: 'blocked' });
  assert.deepEqual(rowState(ready(board({ status: 'running' }), { session: mine() }), demos[0]), { kind: 'running' });
  assert.deepEqual(rowState(ready(board(), { requesting: { demoId: 'gpgpu-nbody', requestId: 'r' } }), demos[1]), { kind: 'blocked' });
});

test('reserved, faulted and offline boards block every demo without repeating the panel', () => {
  assert.deepEqual(rowState(ready(board({ mode: 'project' })), demos[0]), { kind: 'blocked' });
  assert.deepEqual(rowState(ready(board({ status: 'offline' })), demos[0]), { kind: 'blocked' });
});
