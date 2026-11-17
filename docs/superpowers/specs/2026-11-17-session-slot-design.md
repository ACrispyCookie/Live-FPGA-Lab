# One slot for the visitor's session: design

Status: implemented on branch feature/frontend-redesign and deployed to vm2 (2026-11-17). Approved by Jason with the footer taken off the trace and matched to the portfolio's. Builds on `2026-11-17-frontend-redesign-design.md` and `2026-11-17-responsive-and-attention-design.md`; their tokens, taste rules, copy rules and state model still hold.

## Intent

Jason, after using the deployed lab: "Isn't it confusing that the session section moves up when it becomes active? And also the live stage of the session status is never actually reached since that becomes the active session when it goes live." And: "the footer has become a part of the copper traces but can never be reached." Then, approving this design: "I don't think the footer should be a part of the trace at all. Match the footer of the portfolio."

Three things break the sense of one continuous flow:

1. **The session panel jumps when the demo goes live.** On a phone the session panel sits under the board, so Start takes the visitor down to it, but the stage then opens above the board. On desktop the narrow right-hand column suddenly becomes the full-width top of the page. The card the visitor was watching disappears and something new appears in another place. End jumps back.
2. **The "Live" step is dead.** The stage replaces the panel at the instant the session goes live, so the third step is only ever shown in the rare case of an active session without a demo URL. Nobody sees it reached.
3. **The footer is on the trace and its pad never lights.** The trace draws down to a line 78 % of the way down the viewport. At the bottom of the page the footer sits at 87 to 91 % (measured at 1440 and 390), so its pad stays dark. More to the point, the portfolio's footer isn't on the trace at all, so the lab's shouldn't be either.

Success: from pressing Start to ending the session, the visitor's attention stays on one card that grows into the demo and shrinks back, and its three steps all visibly complete. The page ends the way njason.dev ends.

## Goals

- The visitor's own panel holds a single place on the page from Start until the session's end message: the first slot of the hero.
- The stage visibly grows out of that panel and shrinks back into it on End.
- The "Live" step is reached on screen, inside the stage, while the demo page loads.
- The footer matches the portfolio's and sits off the trace; scrolled to the bottom, the whole trace is drawn and every pad is lit.

## Non-goals

- No change to the backend, the protocol, the reducer's state shape or the copy voice.
- No change to the idle and busy layouts: an idle visitor still sees the board first.
- No new controls; the stage bar's actions stay as they are.

## Anti-goals (failure even if it works)

- Motion that runs without the visitor causing it, or that plays when reduced motion is on.
- A layout change the visitor didn't cause that moves content under their finger. The only reorder happens as part of the Start they just pressed, when the page is taking them to the panel anyway.
- Any frame where the old panel and the new stage are both gone (a blank hero), or where the trace's stub runs across a panel.

## Approaches considered

1. **Grow the stage out of the panel (chosen with Jason).** One slot for the visitor's session at every width; a view transition morphs the panel into the stage; the progress card becomes the stage's loading cover, where "Live" is reached.
2. **Keep the layout and drop the "Live" step.** This fixes the dead step but not the jump, and leaves the end of the flow unmarked.
3. **Open the stage as an overlay above the page.** This avoids layout changes, but it's the least like the portfolio (rejected in the previous round for the same reason) and hides the board.

## Design

### A. One slot

A pure `heroLayout(state): 'board-first' | 'session-first' | 'stage'` in `lab/derive.ts` decides the hero:

| Phase | Layout | Hero, in DOM and visual order |
|---|---|---|
| connecting, offline, fault, project, idle, busy | `board-first` | full board panel, then the session panel (as today) |
| requesting, queued, starting, ending, ended | `session-first` | session panel (two shares), then the board in its compact form (one share) |
| active with a demo URL | `stage` | stage (full width), then the compact board |

- The DOM order changes with the layout, so screen readers and keyboard order match what is seen; no CSS `order`.
- While the visitor has something in flight the board shows compact: name and readouts, without the "One real board..." paragraph. The board remains readable but no longer competes with the visitor's card.
- `ended` stays `session-first`, so the end message ("Your ... session ended", Start again) appears where the stage was and keeps that place. The reducer clears `lastEnded` only when the visitor starts again or gets a new live session, so the page doesn't rearrange itself on its own after End. A reload starts from `board-first`.
- **The trace's hero pad belongs to whichever element leads.** Today the board's band carries `data-pad`. Instead, the first element of the hero carries it: the board band in `board-first`, the session panel in `session-first` (pad at the panel's top, stub to its left edge), and the stage bar in `stage`. Exactly one `data-pad` sits in the hero at any time, so the first stub never crosses a panel.

### B. The transition

- Layout changes are wrapped in a same-document view transition (`document.startViewTransition`). Because `reduce` is pure, the app can tell before rendering that an action changes `heroLayout`. A small wrapper around `dispatch` (`useLayoutTransitionDispatch` in `src/lab/transition.ts`) computes `heroLayout(reduce(state, action))` against the current layout. When they differ, it runs the dispatch inside `startViewTransition(() => flushSync(() => dispatch(action)))`. Every other action dispatches normally. Both the socket hook and the local actions use this wrapper.
- `view-transition-name`s:
  - `visitor` on the session panel and on the stage, so the panel morphs into the stage and back;
  - `board` on the board panel, in either form;
  - `progress` on the progress card inside the panel and on the stage's loading cover, so the card the visitor was watching becomes the cover.
- Timing: about 380 ms with the existing `cubic-bezier(.16, 1, .3, 1)` ease, set through `::view-transition-group(*)`.
- If the browser lacks view transitions or reduced motion is on, the swap is instant, with no fallback animation.
- The existing scroll-to-hero on going live and the reveal on Start stay. The reveal's scroll runs after the transition's `updateCallbackDone`, so it measures the new layout.

### C. "Live" is reached in the stage

- While the demo page loads, the stage shows the progress card as its cover: the demo's thumbnail and name, the three steps with Requested and Programming the board done and **Live current**, and the sentence "Opening the demo." (new copy, `copy.session.active.opening`; the existing "Loading the demo" text goes).
- On the frame's `load` event, Live turns done, the card holds for about 500 ms so the completed track is seen, then the cover fades out over 300 ms. Under reduced motion the cover is removed on load with no hold and no fade.
- Pure helper `stageSteps(state, frameLoaded): Step[]`: the result of `progressSteps(state)` with the last step `current` until the frame has loaded, then `done`.
- The panel's own "active without a demo URL" case keeps showing Live as current, as today.

### D. The footer, as on njason.dev

The portfolio's footer (read from the live site on 2026-11-17, `.foot` in `/_astro/Base.*.css`):

- a full-bleed band in `--panel`, edge to edge of the viewport, at the very bottom of the page, after a section gap; top padding 36 px, bottom 28 px plus the safe-area inset;
- an inner grid aligned with the content column, two columns (`minmax(0, 1fr) auto`, items aligned to the end, gap 18 px 24 px), one column on narrow screens with the links aligned to the start;
- left: the name in bold display type at the lead size, with a dim line under it;
- right: dim links that turn silk on hover, no underline, gap 8 px 18 px, wrapping;
- a bottom row across both columns in small dim type: the copyright on the left, a build note on the right.

The lab's footer is the same component with the lab's content:

- **Name and line:** "Jason Nikas", then "Live FPGA Lab: a real board on the bench in my homelab."
- **Links:** "Portfolio" (njason.dev), "Projects" (njason.dev/projects), "GitHub" (github.com/ACrispyCookie), "LinkedIn" (the same profile the portfolio links).
- **Bottom row:** "© <current year> Jason Nikas" and "Source on GitHub" (the lab's repository, the only link in the row).

It sits outside `<main>`, after the trace's wrapper, so the trace ends at the Recent sessions pad. Its inner grid uses the same width and left edge as the content column (`--page`, `--gutter`), so the name lines up with the section headings, the way the portfolio's lines up with its own. The body's bottom padding goes; the band meets the bottom edge. All strings live in `lab/copy.ts`.

### E. The trace is drawn to its end at the bottom of the page

- `Trace.measure()` sets the drawn length to the point at 78 % of the viewport's height. On a short last section, that point can stay above the last pad at maximum scroll (this is how the footer pad stayed dark).
- Fix: when the page is scrolled to within 2 px of its bottom, the target is the whole length (`total`). Nothing else about the drawing changes.

## Tests and checks

- `derive.test.ts`: `heroLayout` for every phase in the table above; `stageSteps` before and after the frame loads.
- `transition.test.ts`: the wrapper's "does this action change the layout" decision (a pure `changesLayout(state, action, now)`), for start.requested from idle (true), a session.updated from queued to starting (false: both `session-first`), session active with a demo URL (true), and a temperature update (false).
- `check.py`:
  - per fixture, the hero's first element is the board (idle, busy, project, fault, offline), the session panel (requesting, queued, starting, ending, ended, failed) or the stage (active), and the hero holds exactly one `[data-pad]`;
  - at maximum scroll every `.t-pad` is lit, at 390, 1440 and 2560;
  - the footer sits outside `.wrap`, spans the viewport's width (±1 px), carries no `data-pad`, and its inner block's left edge equals `main`'s left edge (±1 px);
  - the attention flow (Start from the bottom of the page) still finds the session panel in view and focused, now as the hero's first element.
- `real_flow.py`: one real n-body session at 1440 and one at 390. Record the hero's first element at each change, and confirm the cover shows Live current before the frame loads and is gone after. Run only with the board idle and nobody queued.

## Left to the builder

- The exact transition duration and whether the board's transition needs its own timing.
- How the compact board reads in the narrow one-share column; fall back to its single-column form via the existing container query.
- Whether the ended message needs a small layout tweak in the wide slot.

## Rollout

On `feature/frontend-redesign`, deployed to vm2 only when `/api/public/board` reports idle with an empty queue, since a deploy drops a live session.
