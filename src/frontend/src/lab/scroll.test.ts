import { test } from 'node:test';
import assert from 'node:assert/strict';
import { needsScroll } from './scroll.ts';

test('scrolls only when the panel is not fully in view below the bar', () => {
  assert.equal(needsScroll(80, 500, 900, 62), false);
  assert.equal(needsScroll(40, 500, 900, 62), true); // under the bar
  assert.equal(needsScroll(-300, 100, 900, 62), true); // above the viewport
  assert.equal(needsScroll(700, 1100, 900, 62), true); // below the fold
  assert.equal(needsScroll(62, 900, 900, 62), false); // exactly fits
});
