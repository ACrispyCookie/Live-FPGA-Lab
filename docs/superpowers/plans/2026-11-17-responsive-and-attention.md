# Lab Layout and Attention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the lab page compose well from 320 to 2560 px using content-derived sizes, then make pressing Start take the visitor straight to a clear progress card in the session panel.

**Architecture:** Part 1 is CSS only: the stylesheet's pixel caps and breakpoints are replaced by tokens derived from the type scale and by container queries on the components. The browser check script provides the failing "tests". Part 2 adds two pure derivations (`progressSteps`, `tabTitle`) and a pure scroll predicate (`needsScroll`), tested with Node's test runner. A progress card in `SessionPanel` and scroll, focus and title effects in `App` consume them.

**Tech Stack:** React 19 + TypeScript + Vite 6 (unchanged), plain CSS with container queries, Node 24 test runner, Python Playwright with system Chrome for browser checks.

**Spec:** `docs/superpowers/specs/2026-11-17-responsive-and-attention-design.md` (and `2026-11-17-frontend-redesign-design.md` for tokens, taste and copy rules).

## Global Constraints

- No arbitrary limits: text measure in `ch`; component sizes in `em`/`rem` from the type scale or from content (`min-content`, `fit-content`, `auto-fit`/`auto-fill`); media by aspect ratio and `cqi`; spacing via `clamp()` over the type scale. Pixel values only for radii, LED dots, trace geometry and hairline offsets. Every cap is a named custom property with a one-line comment giving its derivation.
- Remove: `max-width: 1200px` (`.wrap`, `.topbar .in`, `.foot`), `112px`/`76px` thumbnail columns, `minmax(0, 400px)` hero column, the `1100px` and `760px` media queries (except the token changes they carry, re-expressed), `min-height: 520px` on the frame.
- Palette, fonts and taste rules as in the redesign spec: no borders, shadows, gradients or blur at rest; no ALL-CAPS, eyebrows, arrows or middle dots; cyan only for live/primary.
- Copy lives in `src/frontend/src/lab/copy.ts`: sentence case, no "→", no " · ", no spaced em dash labels.
- Reduced motion: no smooth scroll, no ring, no pulse.
- Check widths: 320, 390, 768, 1280, 1440, 1920, 2560.
- Frontend tests run on vm2 (no Node locally): `scripts/deploy-vm2.sh --no-build && ssh vm2 'cd ~/Live-FPGA-Lab/src/frontend && docker run --rm -v "$PWD":/w -w /w node:24-bookworm-slim node --test --experimental-strip-types "src/**/*.test.ts"'`. This is called **FE-TEST** below.
- Deploy with mock states for checks: `VITE_MOCK_STATES=1 scripts/deploy-vm2.sh`, called **DEPLOY** below. Checks run against it: `.venv-checks/bin/python src/frontend/checks/check.py --chrome /usr/bin/google-chrome-stable`, called **CHECK** below.
- Commit to `feature/frontend-redesign`; never push.

## Review Focus

1. Long demo names or descriptions (an untracked vm2 demo with a 60-character name) in the narrow card layout: the title wraps, and Start never overlaps the tag or leaves the card.
2. Start pressed while the session panel is already on screen (desktop, top of the page): no scroll at all, but focus and the ring still happen.
3. Queued visitor whose turn comes while scrolled to the bottom or in a background tab: the scroll repeats, and the tab title changes to "Programming the board".
4. Programming fails (session ends with `programming_failed`): the track shows the failed step, "Try again" restarts that demo once (double-click guard holds), and the title restores.
5. Viewport resized across the hero's stack point while a session is live: no horizontal overflow, the trace re-measures, and the footer pad stays aligned.

Each line is pinned by a test or check in the owning task (Task 1 covers 1 and 5 via fixtures × widths; Task 4 covers 2 to 4 in unit tests; Task 5 covers 2 in the flow check).

---

## Part 1: layout

### Task 1: Layout checks (the failing tests for Part 1)

**Files:**
- Modify: `src/frontend/checks/check.py`
- Modify: `src/frontend/src/dev/fixtures.ts` (add a `longname` fixture)

**Interfaces:**
- Produces: `check_layout(page, name, width, failures)` gains three checks; `WIDTHS = [320, 390, 768, 1280, 1440, 1920, 2560]`; `FIXTURES` gains `"longname"`.

- [ ] **Step 1: Add the three assertions to `check_layout`**

```python
# footer aligned with the content column
fx = page.evaluate("(() => { const f = document.querySelector('.foot'), m = document.querySelector('main'); return f && m ? f.getBoundingClientRect().left - m.getBoundingClientRect().left : null })()")
if fx is None or abs(fx) > 1: failures.append(f"{name}@{width}: footer is {fx}px off the content edge")
# thumbnails carry their row
small = page.evaluate("[...document.querySelectorAll('.demo')].filter(r => { const t = r.querySelector('.thumb'); return t && t.offsetWidth < 0.25 * r.offsetWidth }).length")
if small: failures.append(f"{name}@{width}: {small} thumbnail(s) under a quarter of their row")
# no body line past 80 characters
long = page.evaluate("""(() => { const out = []; for (const p of document.querySelectorAll('main p')) {
  if (!p.offsetParent) continue; const s = document.createElement('span'); s.textContent = '0'; s.style.visibility = 'hidden'; p.appendChild(s);
  const ch = s.getBoundingClientRect().width; s.remove(); const n = p.clientWidth / ch; if (n > 80) out.push(Math.round(n)); } return out })()""")
if long: failures.append(f"{name}@{width}: paragraph measure {long} ch (max 80)")
```

- [ ] **Step 2: Add the `longname` fixture**

In `fixtures.ts`, add `longname`: `idle` with one extra demo whose name is `GPGPU deferred-shading cathedral flythrough with volumetric fog` and a 160-character description. Add `"longname"` to `FIXTURES` in `check.py`.

- [ ] **Step 3: Run the checks against the current deployment and watch them fail**

Run: DEPLOY, then CHECK
Expected: FAIL. Footer offset failures at every width, thumbnail failures at 1280 to 2560 (two-column rows) and 390, and measure failures at 1920 to 2560 if any. Write the failure counts into the ledger.

- [ ] **Step 4: Commit**

```bash
git add src/frontend/checks/check.py src/frontend/src/dev/fixtures.ts
git commit -m "test(frontend): layout checks for footer alignment, thumbnail size, measure, 320-2560 px"
```

### Task 2: Shell, footer and hero

**Files:**
- Modify: `src/frontend/src/styles.css` (`:root` tokens, `.topbar .in`, `.wrap`, `.foot`, `.hero`, `.readouts`, `.board.compact .body`, the two media queries)
- Modify: `src/frontend/src/App.tsx` (footer moves inside `<main>` as the last child, with `data-pad` on it)

**Interfaces:**
- Consumes: Task 1's checks.
- Produces: CSS custom properties used by Task 3: `--measure` (65ch), `--card` (the demo card's minimum width), `--page` (the content cap), `--gutter`, `--trace-x`, `--gap`.

- [ ] **Step 1: Tokens in `:root`**

Define and comment each:
- `--card: calc(10em + 34ch + 7em)`: thumbnail + description measure + button.
- `--page: calc(3 * var(--card) + 2 * var(--gap-s))`: three cards at most.
- `--gutter: clamp(2.5rem, 5vw, 4.5rem)` and `--trace-x: calc(var(--gutter) * .27)`: keeps today's ratio of 18.5/68.
- `--gap-s: clamp(.6rem, 1vw, .9rem)`.

Keep `--bar` as is (it is the bar's drawn height).

- [ ] **Step 2: Shell**

`.wrap` and `.topbar .in` become `width: min(100%, var(--page) + var(--gutter))`, centred. The footer goes into `<main>` as the last element with `data-pad`, loses its own `padding-left` and `max-width`, and takes `margin-top: var(--gap)`. Delete the `760px` block's gutter overrides, since the clamps replace them.

- [ ] **Step 3: Hero**

`.hero { grid-template-columns: repeat(auto-fit, minmax(min(100%, 22em), 1fr)) }` with the board spanning 2 when there is room. Express this as `.hero { display: flex; flex-wrap: wrap }` with `.board { flex: 2 1 30em }` and `.session { flex: 1 1 20em }`, where the session's basis comes from its heading at the display size. Pick whichever passes the checks with less CSS, and ledger the choice. The board and the session become `container-type: inline-size`. `.readouts` uses `repeat(auto-fit, minmax(min(100%, 9em), 1fr))`. `.board.compact .body` uses a `@container` rule instead of the 760 px media query.

- [ ] **Step 4: Run the checks**

Run: DEPLOY, then CHECK
Expected: no footer or overflow failures at any width, and no measure failures. Thumbnail failures remain (Task 3).

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src/styles.css src/frontend/src/App.tsx
git commit -m "feat(frontend): fluid shell from content-derived tokens, footer on the trace, self-sizing hero"
```

### Task 3: Demo cards, recent list, stage

**Files:**
- Modify: `src/frontend/src/styles.css` (`.demolist`, `.demo*`, `.rec`/recent list, `.stage`, `.frame`, the remaining `760px` rules)
- Modify: `src/frontend/src/components/DemoList.tsx` (wrap the tag and button in a `.foot-line` element so the narrow layout can place them on one line; skeleton rows mirror the structure)

**Interfaces:**
- Consumes: `--card`, `--gap-s` from Task 2.

- [ ] **Step 1: Grid and container**

`.demolist { grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--card)), 1fr)); gap: var(--gap-s) }`, and `.demo { container: demo / inline-size }`.

- [ ] **Step 2: Wide card (default)**

Columns `minmax(0, 32cqi) minmax(0, 1fr) auto`, centred vertically; thumbnail `aspect-ratio: 120 / 76`; `.foot-line` shows the tag only (the button sits in the third column via `display: contents` or grid placement).

- [ ] **Step 3: Narrow card**

`@container demo (inline-size < calc(10em + 34ch))`: one column; thumbnail full width at `aspect-ratio: 2 / 1` with the SVG at `object-fit: contain` on `--raised`; then the text; then `.foot-line` as flex `space-between` with the tag left and Start right.

- [ ] **Step 4: Recent and stage**

`.recent` list uses `repeat(auto-fill, minmax(min(100%, 30em), 1fr))`. The `.frame iframe` loses `min-height: 520px`, and the stage keeps its viewport-derived `min-height`. Under `@container` on the hero (inline-size `< 40em`), the frame takes `aspect-ratio: 4 / 3` and the stage drops its viewport min-height. Remove the `760px` media block if nothing is left in it.

- [ ] **Step 5: Run the checks and look at the screenshots**

Run: DEPLOY, then CHECK
Expected: `OK` with every fixture at every width, including `longname`. Read the screenshots for `idle` at 390, 1280, 1920 and 2560, and for `longname` at 320 and 768. Tune `--card` and the banner ratio by eye if a card looks squeezed or stretched, and ledger the final values.

- [ ] **Step 6: Commit, and send Jason the 390/1440/2560 idle screenshots**

```bash
git add src/frontend/src/styles.css src/frontend/src/components/DemoList.tsx
git commit -m "feat(frontend): self-sizing demo cards with large thumbnails, two-column recent list, viewport-sized stage"
```

---

## Part 2: attention on Start

### Task 4: Progress, title and scroll derivations

**Files:**
- Modify: `src/frontend/src/lab/derive.ts`, `src/frontend/src/lab/copy.ts`
- Create: `src/frontend/src/lab/scroll.ts`, `src/frontend/src/lab/scroll.test.ts`
- Test: `src/frontend/src/lab/derive.test.ts`

**Interfaces:**
- Produces:
  - `type StepState = 'done' | 'current' | 'ahead' | 'failed'`
  - `type Step = { key: 'requested' | 'programming' | 'live'; label: string; state: StepState }`
  - `progressSteps(state: LabState): Step[] | null`
  - `tabTitle(state: LabState): string`
  - `needsScroll(top: number, bottom: number, viewportHeight: number, barHeight: number): boolean` in `scroll.ts`
  - copy: `copy.session.steps = { requested: 'Requested', programming: 'Programming the board', live: 'Live' }`, `copy.session.failed = { head: (d) => \`Programming the board for ${d} failed\`, retry: 'Try again' }`, `copy.title = { base: 'Live FPGA Lab', programming: 'Programming the board', inLine: (place) => \`${place} in line\`, live: 'Your demo is live' }`

- [ ] **Step 1: Write the failing tests**

In `derive.test.ts` (using the file's `ready`, `session`, `board` helpers):

```ts
const states = (s: LabState) => progressSteps(s)?.map((x) => x.state);
test('progress steps follow the request', () => {
  assert.equal(progressSteps(ready()), null);
  assert.deepEqual(states(ready({ requesting: { demoId: 'gpgpu-nbody', requestId: 'r' } })), ['current', 'ahead', 'ahead']);
  assert.deepEqual(states(ready({ session: session({ status: 'starting' }) })), ['done', 'current', 'ahead']);
  assert.deepEqual(states(ready({ session: session({ status: 'active' }) })), ['done', 'done', 'current']);
  assert.deepEqual(states(ready({ session: session({ status: 'active', demo_url: '/d' }) })), ['done', 'done', 'done']);
  assert.equal(progressSteps(ready({ session: session({ status: 'queued' }) })), null);
  assert.deepEqual(states(ready({ lastEnded: session({ status: 'ended', end_reason: 'programming_failed' }) })), ['done', 'failed', 'ahead']);
  assert.equal(progressSteps(ready({ lastEnded: session({ status: 'ended', end_reason: 'user_ended' }) })), null);
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
```

In `scroll.test.ts`:

```ts
test('scrolls only when the panel is not fully in view below the bar', () => {
  assert.equal(needsScroll(80, 500, 900, 62), false);
  assert.equal(needsScroll(40, 500, 900, 62), true);   // under the bar
  assert.equal(needsScroll(-300, 100, 900, 62), true); // above
  assert.equal(needsScroll(700, 1100, 900, 62), true); // below the fold
  assert.equal(needsScroll(62, 900, 900, 62), false);  // exactly fits
});
```

Match the field names in the `requesting` fixture to `LabState['requesting']` in `types.ts`. If they differ, adjust the test literal (not the type) and ledger it.

- [ ] **Step 2: Run them and watch them fail**

Run: FE-TEST
Expected: FAIL with "progressSteps is not a function" or a module-not-found for `scroll.ts`.

- [ ] **Step 3: Implement**

`progressSteps`: `phase()` `requesting` gives current/ahead/ahead; `starting` gives done/current/ahead; `active` gives done/done and then `done` if `session.demo_url` else `current`. When `phase()` is `ended` and `lastEnded.end_reason === 'programming_failed'` it gives done/failed/ahead. Everything else returns `null`. `tabTitle` uses `ordinal` from the same file. `needsScroll` returns `!(top >= barHeight && bottom <= viewportHeight)`. Add the copy.

- [ ] **Step 4: Run all frontend tests and watch them pass**

Run: FE-TEST
Expected: all pass (33 + the new ones), no failures.

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src/lab/derive.ts src/frontend/src/lab/derive.test.ts src/frontend/src/lab/scroll.ts src/frontend/src/lab/scroll.test.ts src/frontend/src/lab/copy.ts
git commit -m "feat(frontend): derive the start progress steps, the tab title and when to scroll to the session"
```

### Task 5: Progress card, scroll, focus and title

**Files:**
- Create: `src/frontend/src/components/Steps.tsx`
- Modify: `src/frontend/src/components/SessionPanel.tsx`, `src/frontend/src/App.tsx`, `src/frontend/src/styles.css`, `src/frontend/src/dev/fixtures.ts` (add a `failed` fixture), `src/frontend/checks/check.py` (flow assertions, `"failed"` in FIXTURES)

**Interfaces:**
- Consumes: `progressSteps`, `tabTitle`, `needsScroll`, the copy from Task 4; `onStart(demoId)` in `App`.
- Produces: `Steps({ steps }: { steps: Step[] })`; `SessionPanel` gains props `onRetry: (demoId: string) => void` and `headingRef: React.Ref<HTMLHeadingElement>`, plus a `flash` boolean.

- [ ] **Step 1: Write the failing flow checks**

In `check.py`'s flow test, run at widths 1440 and 390 on the `idle` fixture. Scroll to the bottom, press Start on the last demo row, and wait 900 ms. Then assert:
- `.session`'s `getBoundingClientRect().top` is between 0 and `innerHeight`;
- `document.activeElement.matches('.session h2')`;
- `document.querySelectorAll('.steps li').length === 3` and the first `li` has `data-state="current"`;
- `document.title === 'Programming the board'`;
- start requests dispatched `== 1` (existing).

Also, on `idle` at 1440 with no scrolling, press the first row's Start and assert `scrollY === 0` afterwards (the panel was already in view, Review Focus 2). Add the `failed` fixture: an idle board and `lastEnded` with `end_reason: 'programming_failed'` for `gpgpu-cube`. Assert that `.steps li[data-state="failed"]` exists and the button text is "Try again".

- [ ] **Step 2: Run them and watch them fail**

Run: DEPLOY, then CHECK `--only idle,failed --widths 390,1440`
Expected: FAIL on scroll position at 1440, focus, steps count, title, and the failed fixture.

- [ ] **Step 3: `Steps` component and panel**

`Steps` renders an `<ol className="steps">` of `<li data-state>` items, each an `Led` (lit for done/current, `blink` for current unless reduced motion, fault colour for failed) plus the label. No numbers. In `SessionPanel`, for `requesting`, `starting`, `active`-without-stage and failed-`ended`:
- a header row with the demo's thumbnail (`thumbnail_url`, small, `aspect-ratio: 120/76`) and name;
- `Steps`;
- one sentence in `<p className="now" aria-live="polite">`.

Move `aria-live` off the panel root. The `h2` gets `tabIndex={-1}` and `headingRef`. For failed, the sentence is `copy.session.failed.head(demo)` and the button "Try again" calls `onRetry(lastEnded.demo_id)`. Keep `Cancel` while starting. `flash` adds a class that runs a 1.2 s cyan `outline` fade once (keyframes, `outline-offset` from the panel edge). Under reduced motion it does nothing.

- [ ] **Step 4: `App` effects**

- `onStart` always calls `revealSession()`: measure `heroRef` (or the `.session` element) with `getBoundingClientRect`; if `needsScroll(top, bottom, innerHeight, bar)` (bar = `.topbar` height), scroll it under the bar (smooth unless reduced motion); then `headingRef.current?.focus({ preventScroll: true })` and set `flash` (cleared on `animationend`). This replaces the phone-only `scrollToSession`.
- An effect on `phase` transitions from `queued` to `starting` calls `revealSession()`.
- An effect sets `document.title = tabTitle(state)` on every change.
- `onRetry = onStart`.

- [ ] **Step 5: Run the checks**

Run: FE-TEST, then DEPLOY, then CHECK (all fixtures, all widths)
Expected: FE-TEST all pass; CHECK `OK`, including the flow assertions and the reduced-motion pass.

- [ ] **Step 6: Commit**

```bash
git add src/frontend/src/components/Steps.tsx src/frontend/src/components/SessionPanel.tsx src/frontend/src/App.tsx src/frontend/src/styles.css src/frontend/src/dev/fixtures.ts src/frontend/checks/check.py
git commit -m "feat(frontend): Start takes the visitor to a progress card with steps, focus and a live tab title"
```

### Task 6: Real session run and docs

**Files:**
- Modify: `src/frontend/checks/real_flow.py` (log `.steps li[data-state=current]` text and `document.title` on each change)
- Modify: `docs/superpowers/specs/2026-11-17-responsive-and-attention-design.md` (status line)

- [ ] **Step 1: Extend `real_flow.py`**

Include `step='<current step label>' title='<document.title>'` in each `changed:` log line, and fail if the title is not `Programming the board` within 2 s of Start.

- [ ] **Step 2: Run a real session**

Run: `.venv-checks/bin/python src/frontend/checks/real_flow.py --chrome /usr/bin/google-chrome-stable --demo gpgpu-nbody`
Expected: `OK`. The log shows step `Requested` then `Programming the board` then the stage, and the title goes `Programming the board`, then `Your demo is live`, then `Live FPGA Lab` after End. (Needs the board free and in demo mode; HDMI demos are still blocked by the capture card, so use n-body.)

- [ ] **Step 3: Update the spec status and commit**

Status: "implemented on branch feature/frontend-redesign and deployed to vm2 (date)".

```bash
git add src/frontend/checks/real_flow.py docs/superpowers/specs/2026-11-17-responsive-and-attention-design.md
git commit -m "chore(frontend): real-session check logs steps and tab title; spec status"
```
