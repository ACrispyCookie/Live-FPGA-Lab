import { test } from 'node:test';
import assert from 'node:assert/strict';
import { autostart } from './autostart.ts';

// A link like https://fpga.njason.dev/?start=gpgpu-nbody joins the queue for that demo on arrival, once.
const demos = [{ id: 'gpgpu-nbody', name: 'GPGPU n-body simulator' }, { id: 'dvd-logo-video', name: 'DVD Logo HDMI' }];
const idle = { demos, hasSession: false, reserved: false };

test('a known demo with nothing in the way: start it', () => {
  assert.deepEqual(autostart('?start=gpgpu-nbody', idle), { action: 'start', demo: demos[0] });
  assert.deepEqual(autostart('?x=1&start=dvd-logo-video', idle), { action: 'start', demo: demos[1] });
});

test('no start parameter: nothing to do, and nothing to strip from the address', () => {
  assert.deepEqual(autostart('', idle), { action: 'none' });
  assert.deepEqual(autostart('?x=1', idle), { action: 'none' });
});

test('an unknown demo: say so, start nothing', () => {
  assert.deepEqual(autostart('?start=nope', idle), { action: 'skip', message: 'That demo is not available right now.' });
});

test('already in a session or the queue: keep it, start nothing new', () => {
  assert.deepEqual(autostart('?start=gpgpu-nbody', { ...idle, hasSession: true }), { action: 'skip', message: 'You already have a session, so nothing new was started.' });
});

test('the board is reserved for projects: start nothing', () => {
  assert.deepEqual(autostart('?start=gpgpu-nbody', { ...idle, reserved: true }), { action: 'skip', message: 'The board is reserved for projects right now.' });
});

test('the address without the start parameter keeps everything else', async () => {
  const { withoutStart } = await import('./autostart.ts');
  assert.equal(withoutStart('/?start=gpgpu-nbody', ''), '/');
  assert.equal(withoutStart('/?x=1&start=gpgpu-nbody', '#top'), '/?x=1#top');
});
