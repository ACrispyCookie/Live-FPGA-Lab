import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reduce } from './reducer.ts';
import {
  boardStatus, demoKind, duration, endedSentence, heroLayout, ordinal, phase, pillText, progressSteps, stageSteps, queueEta, queueSentence, readAgo, recentOutcome, reservedFor, sparkPath, tabTitle, timeLeft,
} from './derive.ts';
import type { Board, LabState, Session } from './types.ts';

const T0 = 1_700_000_000_000;
const iso = (ms: number) => new Date(ms).toISOString();
const board = (over: Partial<NonNullable<Board>> = {}): Board => ({
  device_name: 'Smart Zynq SL', status: 'idle', mode: 'demo', telemetry: { temperature_c: 61.9 }, faults: [], ...over,
});
const demos = [{ id: 'gpgpu-nbody', name: 'GPGPU n-body simulator' }, { id: 'gpgpu-cube', name: 'GPGPU spinning cube' }];
const session = (over: Partial<Session> = {}): Session => ({ id: 's1', demo_id: 'gpgpu-nbody', status: 'queued', created_at: iso(T0), ...over });
const otherActive = (): Session => ({ id: 'o1', demo_id: 'gpgpu-cube', status: 'active', created_at: iso(T0 - 30_000), started_at: iso(T0 - 20_000) });

function ready(over: Partial<LabState> = {}, b: Board = board()): LabState {
  const s = reduce(initialState, { type: 'state.initial', board: b, demos, queue: { length: 0, position: null }, session: null, recent_sessions: [] }, T0);
  return { ...s, ...over };
}

test('phase follows the session and board', () => {
  assert.equal(phase(initialState), 'connecting');
  assert.equal(phase(ready()), 'idle');
  assert.equal(phase(ready({}, board({ mode: 'project', reserved_for: 'thesis work' }))), 'project');
  assert.equal(phase(ready({}, board({ status: 'fault' }))), 'fault');
  assert.equal(phase(ready({}, board({ faults: [{ type: 'over_temperature' }] }))), 'fault');
  assert.equal(phase(ready({}, board({ status: 'offline' }))), 'offline');
  assert.equal(phase(ready({}, null)), 'offline');
  assert.equal(phase(ready({ recent: [otherActive()] }, board({ status: 'running' }))), 'busy');
  assert.equal(phase(ready({ requesting: { demoId: 'gpgpu-nbody', requestId: 'r1' } })), 'requesting');
  assert.equal(phase(ready({ session: session({ status: 'queued' }) })), 'queued');
  assert.equal(phase(ready({ session: session({ status: 'starting' }) })), 'starting');
  assert.equal(phase(ready({ session: session({ status: 'active' }) })), 'active');
  assert.equal(phase(ready({ session: session({ status: 'ending' }) })), 'ending');
  assert.equal(phase(ready({ session: session({ status: 'active' }), endRequested: true })), 'ending');
  assert.equal(phase(ready({ lastEnded: session({ status: 'ended', end_reason: 'user_ended' }) })), 'ended');
  // an own live session wins over the board's project mode until the server ends it
  assert.equal(phase(ready({ session: session({ status: 'active' }) }, board({ mode: 'project' }))), 'active');
});

test('timeLeft appears when expires_at is set later', () => {
  const live = session({ status: 'active', expires_at: null });
  assert.equal(timeLeft(live, T0), null);
  assert.equal(timeLeft({ ...live, expires_at: iso(T0 + 252_000) }, T0), 252);
  assert.equal(timeLeft({ ...live, expires_at: iso(T0 - 5000) }, T0), 0);
});

test('queueEta adds a contended slot per visitor ahead', () => {
  assert.equal(queueEta({ length: 3, position: 2, active_expires_at: iso(T0 + 90_000) }, T0), 90 + 300);
  assert.equal(queueEta({ length: 1, position: 1, active_expires_at: iso(T0 + 90_000) }, T0), 90);
  assert.equal(queueEta({ length: 1, position: 1, active_expires_at: null }, T0), null);
  assert.equal(queueEta({ length: 0, position: null }, T0), null);
});

test('queueSentence and ordinal', () => {
  assert.equal(queueSentence({ length: 3, position: 2 }), '2nd of 3 waiting');
  assert.equal(queueSentence({ length: 1, position: 1 }), '1st of 1 waiting');
  assert.equal(ordinal(1), '1st'); assert.equal(ordinal(2), '2nd'); assert.equal(ordinal(3), '3rd'); assert.equal(ordinal(4), '4th');
  assert.equal(ordinal(11), '11th'); assert.equal(ordinal(12), '12th'); assert.equal(ordinal(13), '13th'); assert.equal(ordinal(21), '21st'); assert.equal(ordinal(22), '22nd');
});

test('duration formats minutes and seconds', () => {
  assert.equal(duration(270), '4m 30s');
  assert.equal(duration(245), '4m 05s');
  assert.equal(duration(45), '45s');
  assert.equal(duration(0), '0s');
});

test('readAgo counts from the last sample', () => {
  assert.equal(readAgo([], T0), null);
  assert.equal(readAgo([{ at: T0 - 2400, c: 61 }], T0), 2);
});

test('sparkPath is empty with fewer than two samples and never contains NaN', () => {
  assert.equal(sparkPath([], 100, 34), '');
  assert.equal(sparkPath([{ at: 1, c: 61 }], 100, 34), '');
  const flat = sparkPath([{ at: 1, c: 61 }, { at: 2, c: 61 }, { at: 3, c: 61 }], 100, 34);
  assert.ok(flat.startsWith('M'));
  assert.ok(!flat.includes('NaN'));
  const rising = sparkPath([{ at: 1, c: 60 }, { at: 2, c: 62 }], 100, 34);
  assert.match(rising, /^M0 \d+(\.\d+)? L100 \d+(\.\d+)?$/);
});

test('demoKind picks the interactive view for n-body only', () => {
  assert.equal(demoKind(demos[0]), 'Interactive 3D view');
  assert.equal(demoKind(demos[1]), 'Live HDMI capture');
});

test('recentOutcome words and tones', () => {
  const ended = (end_reason: string) => recentOutcome(session({ status: 'ended', end_reason }));
  assert.deepEqual(ended('user_ended'), { text: 'Ended by the visitor', tone: 'ok' });
  assert.deepEqual(ended('expired'), { text: 'Time ran out while others were waiting', tone: 'neutral' });
  assert.deepEqual(ended('cancelled'), { text: 'Left the queue', tone: 'neutral' });
  assert.deepEqual(ended('programming_failed'), { text: 'Programming failed', tone: 'bad' });
  assert.deepEqual(ended('fpga_fault'), { text: 'Stopped by a board fault', tone: 'bad' });
  assert.deepEqual(ended('board_offline'), { text: 'Board went offline', tone: 'bad' });
  assert.deepEqual(recentOutcome(session({ status: 'ended', end_reason: 'board_reserved' }), 'thesis work'), { text: 'Board needed for thesis work', tone: 'neutral' });
  assert.deepEqual(ended('board_reserved'), { text: 'Board needed for owner projects', tone: 'neutral' });
  assert.deepEqual(ended('timed_out'), { text: 'Dropped after the visitor left', tone: 'neutral' });
  assert.deepEqual(recentOutcome(session({ status: 'active' })), { text: 'Running now', tone: 'ok' });
});

test('endedSentence names the demo and the reason', () => {
  assert.equal(endedSentence(session({ status: 'ended', end_reason: 'user_ended' }), 'GPGPU n-body simulator'), 'Your GPGPU n-body simulator session ended.');
  assert.equal(endedSentence(session({ status: 'ended', end_reason: 'programming_failed' }), 'GPGPU n-body simulator'), 'Programming the board for GPGPU n-body simulator failed. Try again in a moment.');
  assert.equal(endedSentence(session({ status: 'ended', end_reason: 'expired' }), 'X'), 'Your X session ended: your 5 minutes were up while others were waiting.');
  assert.equal(endedSentence(session({ status: 'ended', end_reason: 'board_reserved' }), 'X', 'thesis work'), 'Your X session ended: the board was needed for thesis work.');
});

test('boardStatus words and tones', () => {
  assert.deepEqual(boardStatus(ready()), { word: 'Idle', tone: 'silk', detail: 'Nothing running' });
  assert.deepEqual(boardStatus(ready({}, board({ mode: 'project', reserved_for: 'thesis work' }))), { word: 'Reserved', tone: 'cyan', detail: 'In use for thesis work' });
  assert.deepEqual(boardStatus(ready({}, board({ mode: 'project' }))), { word: 'Reserved', tone: 'cyan', detail: 'In use for owner projects' });
  assert.equal(reservedFor(ready({}, board({ mode: 'project', reserved_for: 'thesis work' }))), 'thesis work');
  assert.equal(reservedFor(ready()), 'owner projects');
  assert.deepEqual(boardStatus(ready({ recent: [otherActive()] }, board({ status: 'running' }))), { word: 'Running', tone: 'cyan', detail: 'GPGPU spinning cube, another visitor' });
  assert.deepEqual(boardStatus(ready({ session: session({ status: 'active' }) }, board({ status: 'running' }))), { word: 'Running', tone: 'cyan', detail: 'GPGPU n-body simulator, your session' });
  assert.deepEqual(boardStatus(ready({}, board({ status: 'fault', faults: [{ type: 'over_temperature', message: 'Over temperature' }] }))), { word: 'Fault', tone: 'amber', detail: 'Over temperature' });
  assert.deepEqual(boardStatus(ready({}, board({ status: 'offline' }))), { word: 'Offline', tone: 'dim', detail: 'No connection to the board' });
});

test('pillText mirrors the session while its panel is off screen', () => {
  assert.deepEqual(pillText(initialState, true), { text: 'Connecting', tone: 'dim' });
  assert.deepEqual(pillText(ready(), true), { text: 'Idle', tone: 'dim' });
  assert.deepEqual(pillText(ready({}, board({ mode: 'project', reserved_for: 'thesis work' })), true), { text: 'In use for thesis work', tone: 'cyan' });
  assert.deepEqual(pillText(ready({ socket: 'reconnecting' }), true), { text: 'Reconnecting', tone: 'amber' });
  const queued = ready({ session: session({ status: 'queued' }), recent: [otherActive()], queue: { length: 3, position: 2, active_expires_at: iso(T0 + 90_000) } }, board({ status: 'running' }));
  assert.deepEqual(pillText(queued, false), { text: '2nd in line, 6m 30s', tone: 'cyan' });
  assert.deepEqual(pillText(queued, true), { text: 'Running', tone: 'cyan' });
  assert.deepEqual(pillText(ready({ session: session({ status: 'active', expires_at: iso(T0 + 252_000) }) }), false), { text: 'Running, 4m 12s left', tone: 'cyan' });
  assert.deepEqual(pillText(ready({ session: session({ status: 'starting' }) }), false), { text: 'Programming', tone: 'cyan' });
});

const steps = (s: LabState) => progressSteps(s)?.map((x) => x.state);

test('progress steps follow the request', () => {
  assert.equal(progressSteps(ready()), null);
  assert.deepEqual(steps(ready({ requesting: { demoId: 'gpgpu-nbody', requestId: 'r' } })), ['current', 'ahead', 'ahead']);
  assert.deepEqual(steps(ready({ session: session({ status: 'starting' }) })), ['done', 'current', 'ahead']);
  assert.deepEqual(steps(ready({ session: session({ status: 'active' }) })), ['done', 'done', 'current']);
  assert.deepEqual(steps(ready({ session: session({ status: 'active', demo_url: '/d' }) })), ['done', 'done', 'done']);
  assert.equal(progressSteps(ready({ session: session({ status: 'queued' }) })), null);
  assert.deepEqual(steps(ready({ lastEnded: session({ status: 'ended', end_reason: 'programming_failed' }) })), ['done', 'failed', 'ahead']);
  assert.equal(progressSteps(ready({ lastEnded: session({ status: 'ended', end_reason: 'user_ended' }) })), null);
  assert.deepEqual(progressSteps(ready({ session: session({ status: 'starting' }) }))?.map((x) => x.label), ['Requested', 'Programming the board', 'Live']);
});

test('tab title mirrors the visitor own session only', () => {
  assert.equal(tabTitle(initialState), 'Live FPGA Lab');
  assert.equal(tabTitle(ready()), 'Live FPGA Lab');
  assert.equal(tabTitle(ready({ requesting: { demoId: 'gpgpu-nbody', requestId: 'r' } })), 'Programming the board');
  assert.equal(tabTitle(ready({ session: session({ status: 'starting' }) })), 'Programming the board');
  assert.equal(tabTitle(ready({ session: session({ status: 'queued' }), queue: { length: 2, position: 2 } })), '2nd in line');
  assert.equal(tabTitle(ready({ session: session({ status: 'active', demo_url: '/d' }) })), 'Your demo is live');
  assert.equal(tabTitle(ready({ lastEnded: session({ status: 'ended', end_reason: 'programming_failed' }) })), 'Live FPGA Lab');
});

test('the hero leads with the board until the visitor starts something', () => {
  assert.equal(heroLayout(initialState), 'board-first');
  assert.equal(heroLayout(ready()), 'board-first');
  assert.equal(heroLayout(ready({}, board({ status: 'running' }))), 'board-first');
  assert.equal(heroLayout(ready({}, board({ mode: 'project' }))), 'board-first');
  assert.equal(heroLayout(ready({ requesting: { demoId: 'gpgpu-nbody', requestId: 'r' } })), 'session-first');
  for (const status of ['queued', 'starting'] as const) assert.equal(heroLayout(ready({ session: session({ status }) })), 'session-first');
  assert.equal(heroLayout(ready({ session: session({ status: 'active' }) })), 'session-first');
  assert.equal(heroLayout(ready({ session: session({ status: 'active', demo_url: '/d' }) })), 'stage');
  assert.equal(heroLayout(ready({ session: session({ status: 'active', demo_url: '/d' }), endRequested: true })), 'session-first');
  assert.equal(heroLayout(ready({ lastEnded: session({ status: 'ended', end_reason: 'user_ended' }) })), 'session-first');
});

test('the stage reaches Live when its frame loads', () => {
  const live = ready({ session: session({ status: 'active', demo_url: '/d' }) });
  assert.deepEqual(stageSteps(live, false).map((s) => s.state), ['done', 'done', 'current']);
  assert.deepEqual(stageSteps(live, true).map((s) => s.state), ['done', 'done', 'done']);
});
