// Feed a real state.initial message (captured from the deployed lab) through the reducer and every derivation
// the components call, so a payload shape the fixtures never had cannot crash the page silently.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { initialState, reduce } from './reducer.ts';
import { boardStatus, phase, pillText, readAgo, recentOutcome, reservedFor, sparkPath } from './derive.ts';
import { rowState } from './rows.ts';

const file = process.env.LAB_STATE_FILE;

test('a captured state.initial renders without throwing', { skip: !file }, () => {
  const msg = JSON.parse(readFileSync(file!, 'utf8'));
  let s = reduce(initialState, { type: 'socket.opened' }, Date.now());
  s = reduce(s, msg, Date.now());
  assert.equal(s.ready, true);
  const p = phase(s);
  assert.ok(p);
  boardStatus(s); pillText(s, true); pillText(s, false); readAgo(s.temps, Date.now()); sparkPath(s.temps, 100, 34); reservedFor(s);
  for (const r of s.recent) recentOutcome(r);
  for (const d of s.demos) rowState(s, d);
  console.log('phase', p, 'board', boardStatus(s), 'pill', pillText(s, true));
});
