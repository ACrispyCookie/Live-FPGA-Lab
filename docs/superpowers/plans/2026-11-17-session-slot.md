# Session Slot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the visitor's session one slot in the hero that grows into the live demo, reach the "Live" step inside the stage, and end the page with the portfolio's footer, off the trace.

**Architecture:** Three pure functions decide everything new: `heroLayout` and `stageSteps` in `lab/derive.ts`, and `changesLayout` in a new `lab/transition.ts`. All three are unit-tested in Node. `App` renders the hero in `heroLayout` order and wraps layout-changing dispatches in a view transition. `Stage` shows a progress cover until its frame loads. The footer becomes a full-bleed band outside the trace's wrapper. Browser checks pin order, footer geometry and pads; one real session per width confirms the flow.

**Tech Stack:** React 19 + TypeScript + Vite 6, CSS view transitions (`document.startViewTransition`, `view-transition-name`), Node 24 test runner on vm2, Python Playwright with system Chrome.

**Spec:** `docs/superpowers/specs/2026-11-17-session-slot-design.md`

## Global Constraints

- Taste and copy rules from the earlier specs: no borders, shadows, gradients or blur at rest; no ALL-CAPS, eyebrows, "→" or middle dots; cyan only for live/primary; all strings in `src/frontend/src/lab/copy.ts`.
- No arbitrary layout limits: sizes from content, the type scale, `ch`/`em`/`cqi`, or named tokens.
- Reduced motion: no view transition, no cover hold or fade; every swap is instant.
- **Before any deploy or real-session test, `/api/public/board` must report `status: idle` and `queue_length: 0`.** A deploy restarts the web API and drops a live session without resetting the board.
- FE-TEST: `scripts/frontend-test-vm2.sh`. DEPLOY: the board check above, then `VITE_MOCK_STATES=1 scripts/deploy-vm2.sh`. CHECK: `.venv-checks/bin/python -u src/frontend/checks/check.py --chrome /usr/bin/google-chrome-stable` with `--only`/`--widths` subsets per task; a full run (about 20 min) once at the end.
- Commit to `feature/frontend-redesign`; never push.

## Review Focus

1. A queued visitor whose turn comes: `queued` to `starting` keeps `session-first` (no transition), then `starting` to active with a URL runs one transition. Two transitions must never overlap.
2. Socket reconnect while live (`reconnecting` fixture): layout stays `stage`, no transition, and the frame isn't reloaded.
3. The demo frame never fires `load` (blocked or slow): the cover stays with Live current, and End still works from the stage bar.
4. Ending from the stage: `active` to `ending` swaps the stage back to the panel in one transition, and focus doesn't land on a removed element.
5. A phone at 320 px: the session-first hero, the compact board under it and the footer's single column all fit with no horizontal overflow.

---

### Task 1: Footer as on njason.dev, and the trace drawn to its end

**Files:**
- Modify: `src/frontend/checks/check.py`, `src/frontend/src/App.tsx`, `src/frontend/src/styles.css`, `src/frontend/src/lab/copy.ts`, `src/frontend/src/components/Trace.tsx`
- Create: `src/frontend/src/components/Footer.tsx`

**Interfaces:**
- Produces: `Footer()` (no props); `copy.footer = { line: 'Live FPGA Lab: a real board on the bench in my homelab.', links: [{ label: 'Portfolio', href: 'https://njason.dev' }, { label: 'Projects', href: 'https://njason.dev/projects' }, { label: 'GitHub', href: 'https://github.com/ACrispyCookie' }, { label: 'LinkedIn', href: 'https://www.linkedin.com/in/jason-nikas-b64163255' }], copyright: (year: number) => \`© ${year} Jason Nikas\` }`; existing `copy.site.source`/`sourceLabel` are reused for the bottom row.

- [ ] **Step 1: Replace the footer check in `check_layout`.** Remove the "footer is Npx off the content edge" block. Add:
  - `.foot` exists and is not inside `.wrap`;
  - its width equals `innerWidth` minus the scrollbar (±1);
  - it has no `data-pad`;
  - `.foot-in`'s left edge equals `main`'s left edge (±1).

  Add the pad check, which runs once per fixture: scroll to `scrollHeight`, wait 1500 ms, and fail if any `.t-pad` lacks `on`.
- [ ] **Step 2: Run CHECK `--only idle,longname --widths 390,1440,2560` against the current build.** Expected: FAIL on footer-inside-wrap, width and pad-unlit at each width.
- [ ] **Step 3: Implement.**
  - `Footer.tsx` renders `<footer className="foot"><div className="foot-in"><div><b/><p/></div><div className="links">…</div><small><span/>…<a/></small></div></footer>`. External links get `rel="noopener"`.
  - `App` renders it after `.wrap` with no `data-pad`.
  - CSS ports the portfolio's `.foot` rules. The band breaks out of the body's inline padding the same way `.topbar` does. `.foot-in` gets `width: min(100%, calc(var(--page) + var(--gutter)))`, `margin-inline: auto` and `padding-left: var(--gutter)`. A `@container`/flex fallback gives one column when the band is narrower than its two columns' content. Remove `body`'s bottom padding.
  - `Trace.measure()` sets `target = total` when `scrollY + innerHeight >= scrollHeight - 2`.
- [ ] **Step 4: DEPLOY, then CHECK `--only idle,longname,active --widths 320,390,1440,2560`.** Expected: OK. Compare the screenshots of the footer at 1440 and 390 with the portfolio's (`nj-foot-*.png` in the session scratchpad).
- [ ] **Step 5: Commit** `feat(frontend): footer as on njason.dev, off the trace; trace drawn to its end at the bottom`.

### Task 2: The pure decisions

**Files:**
- Modify: `src/frontend/src/lab/derive.ts`, `src/frontend/src/lab/derive.test.ts`, `src/frontend/src/lab/copy.ts`
- Create: `src/frontend/src/lab/transition.ts`, `src/frontend/src/lab/transition.test.ts`

**Interfaces:**
- Produces: `type HeroLayout = 'board-first' | 'session-first' | 'stage'`; `heroLayout(state: LabState): HeroLayout`; `stageSteps(state: LabState, frameLoaded: boolean): Step[]`; `changesLayout(state: LabState, action: Action, now: number): boolean`; `copy.session.active.opening = 'Opening the demo.'` (remove `copy.session.active.loading`).

- [ ] **Step 1: Write the tests.** Use the existing `ready`/`session`/`board` helpers in `derive.test.ts`:

```ts
test('the hero leads with the board until the visitor starts something', () => {
  assert.equal(heroLayout(initialState), 'board-first');
  assert.equal(heroLayout(ready()), 'board-first');
  assert.equal(heroLayout(ready({}, board({ status: 'running' }))), 'board-first');
  assert.equal(heroLayout(ready({}, board({ mode: 'project' }))), 'board-first');
  assert.equal(heroLayout(ready({ requesting: { demoId: 'gpgpu-nbody', requestId: 'r' } })), 'session-first');
  for (const status of ['queued', 'starting'] as const) assert.equal(heroLayout(ready({ session: session({ status }) })), 'session-first');
  assert.equal(heroLayout(ready({ session: session({ status: 'active' }) })), 'session-first'); // live but no URL yet
  assert.equal(heroLayout(ready({ session: session({ status: 'active', demo_url: '/d' }) })), 'stage');
  assert.equal(heroLayout(ready({ session: session({ status: 'active', demo_url: '/d' }), endRequested: true })), 'session-first');
  assert.equal(heroLayout(ready({ lastEnded: session({ status: 'ended', end_reason: 'user_ended' }) })), 'session-first');
});
test('the stage reaches Live when its frame loads', () => {
  const live = ready({ session: session({ status: 'active', demo_url: '/d' }) });
  assert.deepEqual(stageSteps(live, false).map((s) => s.state), ['done', 'done', 'current']);
  assert.deepEqual(stageSteps(live, true).map((s) => s.state), ['done', 'done', 'done']);
});
```

In `transition.test.ts`, assert that `changesLayout` is:
- true for `start.requested` from idle;
- false for `session.updated` from queued to starting;
- true for `session.updated` to active with a `demo_url` from starting;
- false for `board.updated` with a new temperature.
- [ ] **Step 2: Run FE-TEST.** Expected: FAIL (missing exports or module).
- [ ] **Step 3: Implement.** `heroLayout` from `phase()` and `session.demo_url` per the spec's table, where `ending` is session-first because the stage is gone. `stageSteps` maps `progressSteps(state)`, with the last step `current` until `frameLoaded`. `changesLayout(s, a, now)` returns `heroLayout(reduce(s, a, now)) !== heroLayout(s)`.
- [ ] **Step 4: Run FE-TEST.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(frontend): derive the hero layout, the stage's steps and which actions change the layout`.

### Task 3: One slot

**Files:**
- Modify: `src/frontend/src/App.tsx`, `src/frontend/src/components/BoardPanel.tsx`, `src/frontend/src/components/SessionPanel.tsx`, `src/frontend/src/components/Stage.tsx`, `src/frontend/src/styles.css`, `src/frontend/checks/check.py`

**Interfaces:**
- Consumes: `heroLayout`.
- Produces: `BoardPanel` prop `lead: boolean` (carries `data-pad` on its band only when true); `SessionPanel` prop `lead: boolean` (puts `data-pad` on its root when true); `Stage` always carries `data-pad` on its `.sbar`.

- [ ] **Step 1: Add the hero-order check.** Per fixture, the first child of `.hero` matches `.board` for idle, busy, project, fault, offline and connecting; `.session` for requesting, queued, starting, ending, ended and failed; `.stage` for active and reconnecting. `.hero [data-pad]` count is exactly 1, and that element is the first child or inside it.
- [ ] **Step 2: Run CHECK `--only idle,queued,starting,ended,active --widths 390,1440`.** Expected: FAIL on order for queued, starting and ended (the board leads today), and on the pad check for active (today the pad sits on the compact board's band, not on the stage).
- [ ] **Step 3: Implement.** `App` renders the hero children in layout order:
  - `board-first`: full board (lead), then session;
  - `session-first`: session (lead), then the compact board;
  - `stage`: stage, then the compact board.

  `.hero.session-first > .session { flex: 2 1 30em }` and `.hero.session-first > .board { flex: 1 1 20em }`. The existing `stage-first` rule stays for the stage. `revealSession` still finds `.session` and focuses its heading.
- [ ] **Step 4: DEPLOY, then CHECK `--only idle,busy,requesting,queued,starting,active,ending,ended,failed,reconnecting --widths 320,390,1440`.** Expected: OK, including the attention flow.
- [ ] **Step 5: Commit** `feat(frontend): the visitor's session holds the hero's first slot from Start to its end`.

### Task 4: Grow into the stage, and reach Live

**Files:**
- Create: `src/frontend/src/lab/useLayoutTransitionDispatch.ts`
- Modify: `src/frontend/src/App.tsx`, `src/frontend/src/components/Stage.tsx`, `src/frontend/src/components/SessionPanel.tsx`, `src/frontend/src/styles.css`, `src/frontend/checks/check.py`

**Interfaces:**
- Consumes: `changesLayout`, `stageSteps`, `Steps`, `DemoThumb`.
- Produces: `useLayoutTransitionDispatch(dispatch, getState): Dispatch<Action>`. `getState` reads a ref kept current by `App`. It starts a view transition only when `changesLayout` is true, `document.startViewTransition` exists, reduced motion is off and no transition is running; otherwise it dispatches directly.

- [ ] **Step 1: Add the stage-cover check.** On the `active` fixture at 1440 and 390, the frame (`about:blank`) loads at once. Assert that `.stage .cover` exists in the first 200 ms after navigation, and that within 1500 ms no `.stage .cover` remains. The cover's state before `load` (Live current) is covered by `stageSteps`' unit test and by `real_flow.py` in Task 5, since a mock frame can't be held unloaded.
- [ ] **Step 2: Run CHECK `--only active --widths 1440`.** Expected: FAIL (no `.cover`).
- [ ] **Step 3: Implement.**
  - **The cover.** In `Stage`, a `.cover` holds the pick (thumbnail and name), `Steps` from `stageSteps(state, loaded)` and `copy.session.active.opening`. On `load`: set `loaded`, then after 500 ms add `.out` (opacity transition 300 ms), and remove the cover on `transitionend`. Under reduced motion, remove it on `load`.
  - **The transition wrapper.** `App` passes `useLayoutTransitionDispatch(dispatch, () => stateRef.current)` to `useLabSocket` and uses it for local actions.
  - **Names.** `view-transition-name: visitor` on `.session` and `.stage`, `board` on `.board`, `progress` on the panel's progress block (the `.pick`, `.steps` and `.now` wrapped in `.progress`) and on `.stage .cover`.
  - **Timing.** `::view-transition-group(*) { animation-duration: .38s; animation-timing-function: cubic-bezier(.16, 1, .3, 1); }`.
  - **Reveal after the swap.** `revealSession` and the stage scroll wait for `transition.updateCallbackDone` when a transition is running, kept on a ref.
- [ ] **Step 4: Run FE-TEST, DEPLOY, then CHECK `--only idle,requesting,starting,active,ending,ended,reconnecting --widths 390,1440`, and the reduced-motion pass.** Expected: OK.
- [ ] **Step 5: Commit** `feat(frontend): the session panel grows into the stage, whose cover reaches Live as the demo loads`.

### Task 5: Real sessions and the full check

**Files:**
- Modify: `src/frontend/checks/real_flow.py`, `docs/superpowers/specs/2026-11-17-session-slot-design.md` (status line)

- [ ] **Step 1: Extend `real_flow.py`.** Add `--width`/`--height` (default 1440 × 900; phone sizes use mobile emulation). On each change, log the hero's first child class. After the stage appears, log whether `.stage .cover` is present and its current step. Fail if the stage's first frame lacks a cover with `Live` current, or if a cover remains 3 s after the frame's `load`.
- [ ] **Step 2: With the board idle and the queue empty, run `real_flow.py` for `gpgpu-nbody` at 1440 × 900 and at 390 × 844, and for `dvd-logo-video` at 390 × 844.** Expected: `OK` each time. The logged order goes board, then session, then stage, then session.
- [ ] **Step 3: Run the full CHECK (all fixtures, all widths) in the background.** Expected: `OK`.
- [ ] **Step 4: Commit** `chore(frontend): real-session check follows the hero slot and the stage cover; spec status`.
