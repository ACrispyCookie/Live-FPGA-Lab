import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reduce, TEMP_MAX_SAMPLES, TEMP_WINDOW_MS } from './reducer.ts';
import type { Board, LabState, Session } from './types.ts';

const T0 = 1_700_000_000_000;
const board = (temperature: number | null = 61.9, extra: Partial<NonNullable<Board>> = {}): Board => ({
  device_name: 'Smart Zynq SL', status: 'idle', mode: 'demo', telemetry: { temperature_c: temperature }, faults: [], ...extra,
});
const demos = [{ id: 'gpgpu-nbody', name: 'GPGPU n-body simulator' }, { id: 'dvd-logo-video', name: 'DVD Logo HDMI' }];
const session = (over: Partial<Session> = {}): Session => ({
  id: 's1', demo_id: 'gpgpu-nbody', status: 'queued', created_at: new Date(T0).toISOString(), ...over,
});

function ready(): LabState {
  return reduce(initialState, { type: 'state.initial', board: board(), demos, queue: { length: 0, position: null }, session: null, recent_sessions: [] }, T0);
}

test('state.initial fills the state and marks it ready', () => {
  const s = ready();
  assert.equal(s.ready, true);
  assert.deepEqual(s.demos, demos);
  assert.equal(s.board?.device_name, 'Smart Zynq SL');
  assert.deepEqual(s.temps, [{ at: T0, c: 61.9 }]);
  assert.equal(s.session, null);
});

test('board.updated appends a temperature sample and trims the window', () => {
  let s = ready();
  for (let i = 1; i <= TEMP_MAX_SAMPLES + 5; i++) s = reduce(s, { type: 'board.updated', board: board(60 + i / 100) }, T0 + i * 1000);
  assert.equal(s.temps.length, TEMP_MAX_SAMPLES);
  assert.equal(s.temps[s.temps.length - 1].c, 60 + (TEMP_MAX_SAMPLES + 5) / 100);

  let w = ready();
  w = reduce(w, { type: 'board.updated', board: board(62) }, T0 + TEMP_WINDOW_MS + 1);
  assert.deepEqual(w.temps, [{ at: T0 + TEMP_WINDOW_MS + 1, c: 62 }]);
});

test('null temperature adds no sample', () => {
  let s = ready();
  s = reduce(s, { type: 'board.updated', board: board(null) }, T0 + 1000);
  assert.equal(s.temps.length, 1);
  assert.equal(s.board?.telemetry?.temperature_c, null);
});

test('start.requested sets requesting', () => {
  const s = reduce(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r1' }, T0);
  assert.deepEqual(s.requesting, { demoId: 'gpgpu-nbody', requestId: 'r1' });
  assert.equal(s.lastError, null);
});

test('a second request while requesting is ignored', () => {
  const s = reduce(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r1' }, T0);
  const again = reduce(s, { type: 'start.requested', demoId: 'dvd-logo-video', requestId: 'r2' }, T0 + 10);
  assert.equal(again, s);
});

test('a request while a session is live is ignored', () => {
  let s = reduce(ready(), { type: 'session.updated', session: session({ status: 'active' }) }, T0);
  const again = reduce(s, { type: 'start.requested', demoId: 'dvd-logo-video', requestId: 'r2' }, T0 + 10);
  assert.equal(again, s);
});

test('command.result ok clears requesting', () => {
  let s = reduce(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r1' }, T0);
  s = reduce(s, { type: 'command.result', request_id: 'r1', ok: true, session_id: 's1' }, T0 + 50);
  assert.equal(s.requesting, null);
  const other = reduce(reduce(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r1' }, T0), { type: 'command.result', request_id: 'zzz', ok: true }, T0);
  assert.deepEqual(other.requesting, { demoId: 'gpgpu-nbody', requestId: 'r1' });
});

test('a failed create reverts and keeps the error', () => {
  let s = reduce(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r1' }, T0);
  s = reduce(s, { type: 'command.result', request_id: 'r1', ok: false, error: { code: 'reserved_for_projects', message: 'The FPGA is currently reserved for owner projects.' } }, T0 + 50);
  assert.equal(s.requesting, null);
  assert.equal(s.lastError, 'The FPGA is currently reserved for owner projects.');
  assert.equal(reduce(s, { type: 'error.dismissed' }, T0).lastError, null);
});

test('session.updated with a live session clears requesting and the error', () => {
  let s = reduce(ready(), { type: 'start.requested', demoId: 'gpgpu-nbody', requestId: 'r1' }, T0);
  s = { ...s, lastError: 'old' };
  s = reduce(s, { type: 'session.updated', session: session({ status: 'queued' }) }, T0);
  assert.equal(s.requesting, null);
  assert.equal(s.lastError, null);
  assert.equal(s.session?.id, 's1');
});

test('session.updated to ended moves it to lastEnded and recent', () => {
  let s = reduce(ready(), { type: 'session.updated', session: session({ status: 'active', started_at: new Date(T0).toISOString() }) }, T0);
  const older = session({ id: 'old', status: 'ended', created_at: new Date(T0 - 60_000).toISOString(), started_at: new Date(T0 - 60_000).toISOString(), end_reason: 'user_ended' });
  s = reduce(s, { type: 'recent_sessions.updated', sessions: [older] }, T0);
  const ended = session({ status: 'ended', started_at: new Date(T0).toISOString(), ended_at: new Date(T0 + 5000).toISOString(), end_reason: 'user_ended' });
  s = reduce(s, { type: 'session.updated', session: ended }, T0 + 5000);
  assert.equal(s.session, null);
  assert.equal(s.lastEnded?.id, 's1');
  assert.deepEqual(s.recent.map((r) => r.id), ['s1', 'old']);
  assert.equal(s.endRequested, false);

  let many = s;
  for (let i = 0; i < 10; i++) many = reduce(many, { type: 'session.updated', session: session({ id: `x${i}`, status: 'ended', created_at: new Date(T0 + 10_000 + i).toISOString(), end_reason: 'user_ended' }) }, T0 + 10_000 + i);
  assert.equal(many.recent.length, 6);
});

test('end.requested is remembered until the server answers', () => {
  let s = reduce(ready(), { type: 'session.updated', session: session({ status: 'active' }) }, T0);
  s = reduce(s, { type: 'end.requested' }, T0);
  assert.equal(s.endRequested, true);
  s = reduce(s, { type: 'session.updated', session: session({ status: 'ending', end_reason: 'user_ended' }) }, T0);
  assert.equal(s.endRequested, false);
});

test('socket.closed keeps the session', () => {
  let s = reduce(ready(), { type: 'session.updated', session: session({ status: 'active', demo_url: '/api/sessions/s1/demo' }) }, T0);
  s = reduce(s, { type: 'start.requested', demoId: 'dvd-logo-video', requestId: 'r9' }, T0); // ignored: live session
  s = reduce(s, { type: 'socket.closed' }, T0);
  assert.equal(s.socket, 'reconnecting');
  assert.equal(s.session?.id, 's1');
  assert.equal(s.requesting, null);
  assert.equal(s.temps.length, 1);
  assert.equal(s.ready, true);
  assert.equal(reduce(s, { type: 'socket.opened' }, T0).socket, 'connected');
});

test('ui.message adds a toast with a level', () => {
  let s = reduce(ready(), { type: 'ui.message', level: 'warning', message: 'Programming failed.' }, T0);
  assert.equal(s.toasts.length, 1);
  assert.equal(s.toasts[0].level, 'warn');
  assert.equal(s.toasts[0].message, 'Programming failed.');
  s = reduce(s, { type: 'toast.dismissed', id: s.toasts[0].id }, T0);
  assert.equal(s.toasts.length, 0);
  for (let i = 0; i < 6; i++) s = reduce(s, { type: 'ui.message', level: 'error', message: `m${i}` }, T0 + i);
  assert.equal(s.toasts.length, 4);
});

test('tick updates now and nothing else', () => {
  const s = ready();
  const t = reduce(s, { type: 'tick', now: T0 + 1000 }, T0 + 1000);
  assert.equal(t.now, T0 + 1000);
  assert.deepEqual({ ...t, now: s.now }, s);
});

test('info and success messages raise no toast: the session panel already says them', () => {
  let s = reduce(ready(), { type: 'ui.message', level: 'info', message: 'Programming FPGA...' }, T0);
  s = reduce(s, { type: 'ui.message', level: 'success', message: 'Demo ready.' }, T0);
  assert.equal(s.toasts.length, 0);
});
