// Which actions rearrange the hero. The reducer is pure, so the answer is known before React renders, which is what a
// view transition needs: it has to start before the DOM changes.
import { heroLayout } from './derive.ts';
import { reduce } from './reducer.ts';
import type { Action, LabState } from './types.ts';

export function changesLayout(state: LabState, action: Action, now: number): boolean {
  return heroLayout(reduce(state, action, now)) !== heroLayout(state);
}
