# Lab layout and attention: design

Status: implemented on branch feature/frontend-redesign and deployed to vm2 (2026-11-17). Follows `2026-11-17-frontend-redesign-design.md`; everything there (tokens, taste rules, copy rules, state model) still holds.

## Intent

The redesign shipped, and two things are off when it's used on real screens:

1. **Layout.** The footer is indented twice and floats loose from the page, the thumbnails are small (112 px on desktop, 76 px on phones), phone rows are mostly empty space, and on large monitors the page stops at 1200 px with a third of the screen empty while two demo columns squeeze their text.
2. **Attention.** Start sits in the demo list, but the answer ("Programming the board", "You're 2nd in line") appears in the session panel at the top, which on desktop is usually off-screen. The visitor sees a button saying "Starting…" and a small pill, and has to go and look for what happened.

Success: at any width from a 320 px phone to a 2560 px monitor the page looks composed rather than stretched or squeezed. Within a moment of pressing Start, the visitor is looking at one clear statement of where they stand and what happens next.

## Goals

- Fluid shell: the page uses large screens without stretching text, and the footer belongs to the content column and ends the trace.
- Components lay themselves out from the width they get (container queries), not from the screen width.
- Larger thumbnails that carry each row; on narrow cards they run full width across the top.
- On Start (and on autostart from the portfolio), the page takes the visitor to the session panel at every width. The panel shows the request's progress as steps, and the chosen demo stays visibly linked to it.
- Responsiveness ships first and is deployed on its own; the attention work follows.

## Non-goals

- No change to the backend, the WebSocket protocol, the reducer's state model, the copy voice or the palette.
- No overlay or modal for session progress (rejected: least like the portfolio).
- The progress does not answer in place inside the clicked row (rejected: the state would live in two places).
- No browser notifications or sounds.

## Anti-goals (failure even if it works)

- Text lines past about 75 characters, or panels that grow into wide empty slabs on big monitors.
- A page that jumps around: scrolling that fights the visitor, or layout shift when the state changes.
- Motion that runs when nothing changed, or ignores reduced motion.
- A progress display that looks like a generic stepper widget (numbered circles, 01/02/03 chrome).

## Approaches considered

Layout:
1. **Components that size themselves (chosen).** Container queries on the demo row, board panel and session panel; the demo grid adds a column whenever another card fits. This fixes the real cause: rows break because the grid squeezes them, not because the screen is small.
2. Width-band breakpoints (phone/tablet/laptop/wide): predictable, but more rules to keep in sync, and the in-between widths stay fragile.
3. Only widen and enlarge: quick, but leaves phone rows empty.

Attention: **move the visitor to the session (chosen)**, over answering in place and an overlay (see Non-goals).

## Part 1: layout

### Rule: no arbitrary limits (Jason's instruction)

Every size in the layout comes from the content it protects, never from a picked pixel number:

- Text measure in `ch` (body copy around 65ch, already in place; leads and descriptions follow).
- Component sizes in `em`/`rem` derived from the type scale, or from the size of their own content (`min-content`, `fit-content`, `auto-fit`).
- Media by aspect ratio, sized as a share of their container (`cqi`), not in px.
- Spacing from `clamp()` over the type scale, as `--gap` does now.
- Pixel values stay only where they are drawing geometry: radii, LED dots, the trace's line widths and pad radius, hairline offsets.

Wherever a cap is needed, it is written as a named token with its derivation next to it (for example, the demo card's minimum width is "thumbnail + text measure + button"), so nobody has to wonder where it came from. The current `max-width: 1200px` on `.wrap`, `.topbar .in` and `.foot`, the `112px`/`76px` thumbnail columns, the `minmax(0, 400px)` session column, the `1100px`/`760px` breakpoints and the `min-height: 520px` frame all go.

### Shell

- Page width: the content column grows with the screen until it holds as many demo cards as the grid allows at their natural width. The cap is derived (`--card` × the most columns that read well, plus gaps), not stated in px. On a 1920 screen the page fills most of the width; at 2560 it holds three demo columns.
- Side gutters and the trace rail scale with `clamp()` over the type scale; the top bar's inner width follows the same token as the page, so the name and pill line up with the content edges.
- Footer: moves inside the content column (one gutter, not two), ends the trace with a final gold pad, and sits at the same left edge as the panels. Spacing above it equals the gap between sections.

### Hero (board and session)

- A grid that auto-fits two tracks: the board panel takes the larger share, and the session panel's track is sized from its own content (about the width of its longest heading at the display size). When both don't fit at their minimum, they stack. This happens at whatever screen width that is, not at a fixed breakpoint.
- Board readouts use `auto-fit` with a minimum derived from the readout's content, so they go 3 → 2 → 1 as the panel narrows, wherever the panel sits.

### Demo rows

- The grid is `repeat(auto-fill, minmax(min(100%, var(--card)), 1fr))`, where `--card` is derived from the thumbnail, the text measure of a short description and the button.
- Each row is a container (`container-type: inline-size`):
  - **Wide layout** (the card has room): thumbnail on the left at about a third of the card (`cqi`), text in the middle, Start on the right, all vertically centred.
  - **Narrow layout:** thumbnail across the full card width at a banner aspect ratio, then the title and description, then a footer line with the kind tag on the left and Start on the right.
- The thumbnails' SVGs are drawn for a 120:76 box. In the banner layout they are centred on the raised background (`object-fit: contain`), so nothing is cropped or stretched.
- Skeleton rows follow the same two layouts.

### Recent sessions and stage

- Recent rows go to two columns when the column is wide enough to hold two at their natural width (`auto-fill`), otherwise one.
- Stage: the frame's height comes from the viewport (the existing `100vh` rule minus the bar) instead of a pixel minimum. On phones it keeps a 4:3 frame so the bar and End stay visible.

### Checks

`src/frontend/checks/check.py` gains widths 1920 and 2560 (now 320, 390, 768, 1280, 1440, 1920, 2560) and three assertions per fixture and width:

- the footer's left edge equals the content column's left edge (±1 px);
- every thumbnail is at least 25 % of its row's width in the wide layout, or the full card width in the narrow one;
- no line of body text runs past 80 characters (measured as the paragraph's width divided by the width of a `0` in its font).

## Part 2: attention on Start

### What the visitor sees

1. **Press Start** (or arrive through `?start=`). Within one frame:
   - the row's button reads "Starting…" and the row takes the chosen colour (as today);
   - the other rows' Start buttons step back to their blocked note (as today);
   - the page scrolls so the session panel sits under the top bar, at every width. It does not scroll if the panel is already fully in view. Smooth scrolling is used unless reduced motion is on.
2. **The session panel turns into the progress card** for this request. It shows the demo's thumbnail and name (the visual link back to the row they clicked) and a three-step track: *Requested*, *Programming the board*, *Live*. Each step is an LED in the copper/cyan language: the done ones are lit cyan, the current one pulses, and the ones still ahead are dim. Below the track, one sentence says what is happening now and what happens next.
3. **Queued instead:** the track is replaced by the place in line as the headline ("You're 2nd in line"), the ETA, who is on the board now, and "Leave the queue". When the turn comes, the panel moves to the *Programming* step, and if the page is out of view the scroll repeats.
4. **Live:** the stage takes the hero (as today), and the page scrolls to it (as today).
5. **Failed:** the track stops at the failed step, which turns fault red, with the server's message and a "Try again" that restarts the same demo.

### One moment of emphasis

When the progress card first appears, it gets one cyan ring that fades out over about 1.2 s. That is the only new motion, and it answers the visitor's own action. Reduced motion: no ring and no pulse; the current step is shown by its label weight and lit LED.

### Focus and screen readers

- Focus moves to the session panel's heading (`tabindex="-1"`) when the progress card appears, so keyboard users land on it. Pressing Start again from the list stays harmless (the double-start guard already exists).
- The panel's state sentence is in a polite live region, so each step change is announced once.
- The tab title mirrors the state while the visitor's session is in flight ("Programming the board", "2nd in line", "Your demo is live"), so a background tab still tells them; it restores the default when they have no session.

### State and code

- Progress steps derive from the existing `phase()` plus `requesting`; a new pure `progressSteps(state)` in `lab/derive.ts` returns the three steps with `done | current | ahead | failed`. It is unit-tested like the other derivations.
- The page-title text is a pure `tabTitle(state)` in `derive.ts`, also tested.
- Scrolling on every Start replaces the phone-only `scrollToSession` in `App.tsx`.
- New copy goes in `lab/copy.ts` (step labels, the "now/next" sentences, "Try again", the tab titles), following the copy rules: sentence case, no arrows, no middle dots.

### Checks

- `check.py` flow test, at 1440 and 390: press Start in the last demo row, then assert the session panel's top is within the viewport after the scroll, that focus is on its heading, and that a single start request was dispatched.
- `real_flow.py` additionally logs the step track's current step and the document title at each change.

## Left to the builder

- The exact `--card` derivation and the column cap's multiplier, tuned by eye with screenshots at every check width.
- The banner aspect ratio for narrow thumbnails (somewhere between 16:9 and 2:1).
- Exact wording of the "now/next" sentences, within the copy rules.
- Whether the recent list's two-column layout reads well; drop it if it doesn't.

## Rollout

1. Part 1 on `feature/frontend-redesign`, checks green, deployed to vm2, screenshots to Jason.
2. Part 2 on the same branch, tests and checks green, one real session run with `real_flow.py`, deployed to vm2.
