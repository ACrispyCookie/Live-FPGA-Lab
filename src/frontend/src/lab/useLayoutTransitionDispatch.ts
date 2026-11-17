// Dispatch that animates the hero's rearrangements. When an action changes the hero's layout (the panel moving to the
// front, growing into the stage, shrinking back), it runs inside a view transition so the visitor sees one card move
// rather than one vanish and another appear. Everything else, and every action under reduced motion or in a browser
// without view transitions, dispatches as before.
import { useCallback, useRef } from 'react';
import { flushSync } from 'react-dom';
import { changesLayout } from './transition.ts';
import type { Action, LabState } from './types.ts';

type ViewTransition = { finished: Promise<void>; updateCallbackDone: Promise<void> };
type WithViewTransitions = Document & { startViewTransition?: (update: () => void) => ViewTransition };

/** `visible` says whether the hero is on screen: a rearrangement the visitor can't see isn't animated. */
export function useLayoutTransitionDispatch(dispatch: (action: Action) => void, getState: () => LabState, visible: () => boolean) {
  const running = useRef<ViewTransition | null>(null);
  const send = useCallback((action: Action) => {
    const doc = document as WithViewTransitions;
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!doc.startViewTransition || still || running.current || !visible() || !changesLayout(getState(), action, Date.now())) {
      dispatch(action);
      return;
    }
    const vt = doc.startViewTransition(() => { flushSync(() => dispatch(action)); });
    running.current = vt;
    vt.finished.catch(() => undefined).finally(() => { if (running.current === vt) running.current = null; });
  }, [dispatch, getState, visible]);
  /** Resolves once any running rearrangement has finished, so scrolling and focus act on the final layout. */
  const settled = useCallback(() => (running.current ? running.current.finished.catch(() => undefined) : Promise.resolve()), []);
  return { dispatch: send, settled };
}
