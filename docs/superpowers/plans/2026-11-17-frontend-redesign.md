# Live FPGA Lab Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the lab's React UI in the portfolio's circuit-board world, with instant and unmistakable session feedback, restyled embedded demo pages, and per-demo thumbnails, built and deployed on vm2.

**Architecture:** The existing WebSocket protocol stays. A pure reducer (`lab/reducer.ts`) turns socket events and local actions into one `LabState`; pure helpers (`lab/derive.ts`) turn that state into the words and numbers the components show; components are thin. The copper trace is a self-contained component ported from the approved mock. A small backend addition serves an optional thumbnail per demo. The embedded demo pages link one shared `tokens.css` served from the lab's static folder.

**Tech Stack:** Vite 6 + React 19 + TypeScript (existing), `node --test` for pure modules (existing runner), FastAPI (existing), pytest, Python Playwright for browser checks from the workstation, headless Chrome for screenshots, Docker Compose on vm2 for build and deploy.

**Spec:** `docs/superpowers/specs/2026-11-17-frontend-redesign-design.md`. Visual reference: `docs/superpowers/mocks/lab/` (index.html, lab.css, lab.js), approved by Jason on 2026-11-17 with the nav order Session, Demos, Recent and a shimmering skeleton while connecting.

## Global Constraints

- Tokens, exactly: mask `#0b1d21`, panel `#11282d`, raised `#183539`, hover `#1f4248`, lift `#28525a`, silk `#eaf2f1`, dim `#9db6b8`, groove `#183539`, copper `#3b7a82`, cyan `#41e2f2`, ink `#05252a`, gold `#d8b46a`, gold-ring `#a8873f`, led `#5dffa8`, amber `#f0a64a`, fault `#ff6b5e`.
- Fonts: Bricolage Grotesque (display) and Hanken Grotesk (text), self-hosted from `/static/fonts/`. Tabular numerals everywhere. Monospace only inside code.
- Five text sizes: title `clamp(1.9rem, 3.2vw, 2.6rem)`, lead `1.3rem`, body `1.0625rem`/1.6, small `.875rem`, readout `1.25rem`. Nothing under 13 px. Paragraphs max 65ch.
- No borders, shadows, glows, gradients or blur at rest. No eyebrow or ALL-CAPS labels, no "→", no middle dots, no violet. Sentence case.
- Motion: transform and opacity only; the trace reveal is the one orchestrated motion; `prefers-reduced-motion` disables pulse, breathing and rises.
- Layout: content max 1200 px, trace gutter 68 px / trace at 18.5 px (≤760 px: 42 px / 11 px), page gutters 20 px (phone 12/16 px) with safe-area insets, top bar 62 px (phone 56 px).
- Copy lives in `src/frontend/src/lab/copy.ts`; components never contain user-facing strings inline.
- Never show invented live values. Unknown is shown as unknown ("No reading", "Status unavailable").
- Build/deploy: `scripts/deploy-vm2.sh` syncs this checkout to `vm2:~/Live-FPGA-Lab` and runs `docker compose build web-api && docker compose up -d web-api`. Never sync `.env`, `node_modules`, `src/web_api/static` or demo bitstreams. vm2 has 1 CPU and 1 GB RAM: one build per task, not per step.
- Commits: only after Jason has said to commit; until then, stop at the commit step and leave the work in the tree.
- Keep `autostart.ts` and `autostart.test.ts` unchanged in behaviour.

## Review Focus

1. The socket drops while a session is active: the stage must stay mounted with the iframe, the pill reads "Reconnecting", and nothing in the session is cleared (Task 2 reducer test `socket.closed keeps the session`).
2. `expires_at` arrives on an already active session once someone queues: the stage bar must start showing time left without a remount (Task 2 derive test `timeLeft appears when expires_at is set later`).
3. Start pressed twice before the server answers, or on a second demo while requesting: only one `session.create` is sent and the UI never shows two chosen rows (Task 2 reducer test `a second request while requesting is ignored`; Task 5 Playwright check `double click sends one request`).
4. `command.result` with `ok: false` for a `session.create`: the optimistic "Requesting the board" state reverts and the error sentence shows inline in the session panel (Task 2 reducer test `a failed create reverts and keeps the error`).
5. Temperature readings arrive as `null` or stop arriving: the sparkline must not draw NaN paths, the readout says "No reading" and "read N s ago" keeps counting (Task 2 reducer test `null temperature adds no sample`; derive test `readAgo counts from the last sample`).

---

### Task 1: Foundation: tokens, fonts, static fallback, deploy script

**Files:**
- Create: `src/frontend/public/tokens.css`, `src/frontend/public/fonts/bricolage-grotesque-latin-wght-normal.woff2`, `src/frontend/public/fonts/hanken-grotesk-latin-wght-normal.woff2`
- Create: `scripts/deploy-vm2.sh`
- Modify: `src/frontend/package.json` (pin versions: `vite` `^6.3.5`, `@vitejs/plugin-react` `^4.4.1`, `react` and `react-dom` `^19.1.0`, `typescript` `^5.8.3`, `@types/react` `^19.1.2`, `@types/react-dom` `^19.1.2`), `src/frontend/index.html`, `docker/web-api.Dockerfile`
- Modify: `src/frontend/vite.config.ts` (no change in output paths; add `build.assetsInlineLimit: 0` so the two woff2 files are never inlined if ever imported)

**Interfaces:**
- Produces: `/static/tokens.css` defining the custom properties `--mask … --fault`, `--font-display`, `--font-text`, `--t-title`, `--t-lead`, `--t-body`, `--t-small`, `--t-readout`, `--r-xl: 28px`, `--r-l: 22px`, `--r-m: 16px`, the two `@font-face` rules (`font-family: "Bricolage Grotesque"`, `"Hanken Grotesk"`, `font-weight: 200 800` / `100 900`, `font-display: swap`, `src: url(/static/fonts/…)`), a reset (`*{box-sizing:border-box}`, `body{margin:0;background:var(--mask);color:var(--silk);font:var(--t-body)/1.6 var(--font-text);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}`), `::selection`, `:focus-visible` (2px solid cyan, offset 3px) and `scrollbar-color`.
- Produces: `scripts/deploy-vm2.sh` (bash, `set -euo pipefail`), usage `scripts/deploy-vm2.sh [--no-build]`.

- [ ] **Step 1: Fetch the two variable latin font files** from the portfolio's deployed assets (`https://njason.dev/_astro/bricolage-grotesque-latin-wght-normal.DLoelf7F.woff2` and the `hanken-grotesk-latin-wght-normal.*.woff2` name read from `https://njason.dev/_astro/Base.BLAfHFGY.css`) into `src/frontend/public/fonts/` with the un-hashed names above. Verify: `file` reports "Web Open Font Format (Version 2)" for both and each is between 20 KB and 200 KB.

- [ ] **Step 2: Write `src/frontend/public/tokens.css`** with the contents listed under Interfaces. A header comment: `/* Copied from the portfolio's docs/DESIGN_SYSTEM.md (ACrispyCookie/portfolio). Change there first, then here. */`

- [ ] **Step 3: Rewrite `src/frontend/index.html`**: `<html lang="en">`, title "Live FPGA Lab", the existing meta description replaced by "A real FPGA board in Jason Nikas's homelab. Pick a demo and run it on the board from your browser.", `<link rel="preload" as="font" type="font/woff2" crossorigin href="/fonts/…">` for both fonts, `<link rel="stylesheet" href="/tokens.css">`, `<div id="root">` containing a static fallback: a `<main class="fallback">` with the sentence "Live FPGA Lab: a real FPGA board in my homelab. This page needs JavaScript to connect to it." and a link to https://njason.dev. Vite rewrites the `/tokens.css` and `/fonts/` references under `base: '/static/'`.

- [ ] **Step 4: Pin dependency versions in `package.json`** as listed in Files; keep the scripts as they are.

- [ ] **Step 5: Add `RUN npm test --prefix src/frontend` to `docker/web-api.Dockerfile`** right after `RUN npm run build --prefix src/frontend`, so a failing frontend test fails the image build.

- [ ] **Step 6: Write `scripts/deploy-vm2.sh`**: `rsync -az --delete-excluded --exclude node_modules --exclude 'src/web_api/static/' --exclude '.env*' --exclude '*.bit' --exclude '*.elf' --exclude '__pycache__' --exclude '.venv' --exclude 'docs/' ./ vm2:~/Live-FPGA-Lab/` then, unless `--no-build`, `ssh vm2 'cd ~/Live-FPGA-Lab && docker compose build web-api && docker compose up -d web-api && docker compose ps web-api'`. The rsync must not use `--delete` outside excluded paths (the untracked demo folders on vm2 must survive); verify afterwards with `ssh vm2 'ls ~/Live-FPGA-Lab/demos'` listing all eight demos.

- [ ] **Step 7: Deploy and verify**

Run: `scripts/deploy-vm2.sh`
Expected: build succeeds; `curl -sI https://fpga.njason.dev/static/tokens.css | head -1` is `HTTP/2 200`; `curl -s https://fpga.njason.dev/ | grep -c 'tokens.css'` is `1`; `curl -sI https://fpga.njason.dev/static/fonts/hanken-grotesk-latin-wght-normal.woff2 | head -1` is `HTTP/2 200`; the eight demo folders are still on vm2.

- [ ] **Step 8: Commit** (only if Jason has said to commit)

```bash
git add src/frontend/public scripts/deploy-vm2.sh src/frontend/index.html src/frontend/package.json docker/web-api.Dockerfile src/frontend/vite.config.ts
git commit -m "feat(frontend): portfolio tokens, self-hosted fonts, vm2 deploy script"
```

---

### Task 2: State core: types, reducer, derivations, copy

**Files:**
- Create: `src/frontend/src/lab/types.ts`, `src/frontend/src/lab/reducer.ts`, `src/frontend/src/lab/reducer.test.ts`, `src/frontend/src/lab/derive.ts`, `src/frontend/src/lab/derive.test.ts`, `src/frontend/src/lab/copy.ts`
- Modify: `src/frontend/package.json` test script to `node --test --experimental-strip-types "src/**/*.test.ts"` (quoted so the shell does not expand the glob)

**Interfaces:**
- Produces, in `types.ts`: `Board`, `Demo` (`{ id, name, description?, thumbnail_url?: string | null }`), `Session` (fields as the server's `DemoSession` JSON plus `demo_url?: string | null`), `QueueState`, `Toast`, `Phase = 'connecting' | 'offline' | 'fault' | 'project' | 'idle' | 'busy' | 'requesting' | 'queued' | 'starting' | 'active' | 'ending' | 'ended'`, `TempSample = { at: number; c: number }`, `LabState = { socket: 'connecting' | 'connected' | 'reconnecting'; ready: boolean; board: Board; demos: Demo[]; queue: QueueState; session: Session | null; recent: Session[]; requesting: { demoId: string; requestId: string } | null; lastError: string | null; lastEnded: Session | null; temps: TempSample[]; toasts: Toast[] }`, `WsEvent` (discriminated union over the seven server message types with `request_id` on `command.result`), `LocalAction = { type: 'socket.opened' } | { type: 'socket.closed' } | { type: 'start.requested'; demoId: string; requestId: string } | { type: 'end.requested' } | { type: 'toast.dismissed'; id: string } | { type: 'tick'; now: number }`.
- Produces, in `reducer.ts`: `export const initialState: LabState`, `export function reduce(state: LabState, action: WsEvent | LocalAction, now?: number): LabState` (pure; `now` defaults to `Date.now()`), `export const TEMP_WINDOW_MS = 300_000`, `export const TEMP_MAX_SAMPLES = 200`.
- Produces, in `derive.ts`: `phase(state): Phase`; `timeLeft(session, now): number | null` (seconds until `expires_at`); `queueEta(queue, now, contendedSeconds = 300): number | null`; `queueSentence(queue): string` ("2nd of 3 waiting"); `ordinal(n): string`; `duration(seconds): string` ("4m 30s", "45s"); `boardStatus(state): { word: string; tone: 'dim' | 'cyan' | 'amber' | 'silk'; detail: string }`; `pillText(state, sessionVisible: boolean): { text: string; tone: 'dim' | 'cyan' | 'amber' }`; `readAgo(temps, now): number | null`; `sparkPath(temps, width, height): string` ("" when fewer than 2 samples); `demoKind(demo): 'Interactive 3D view' | 'Live HDMI capture'` (n-body is the interactive one, by id `gpgpu-nbody`); `recentOutcome(session): { text: string; tone: 'ok' | 'neutral' | 'bad' }`; `endedSentence(session, demoName): string`.
- Produces, in `copy.ts`: one exported object `copy` holding every sentence from the spec's state table and interaction-flow section, keyed by phase and situation, with functions for sentences that take a demo name or number.

- [ ] **Step 1: Write the failing reducer tests** in `reducer.test.ts` using `node:test` and `node:assert/strict`, one `test()` each:

```ts
test('state.initial fills the state and marks it ready', …)          // ready true, demos copied, temps gets one sample when temperature_c is a number
test('board.updated appends a temperature sample and trims the window', …) // 201 samples → 200; samples older than TEMP_WINDOW_MS dropped
test('null temperature adds no sample', …)
test('start.requested sets requesting and sends nothing twice', …)   // second start.requested while requesting leaves state unchanged (same object)
test('a second request while requesting is ignored', …)
test('command.result ok clears requesting', …)
test('a failed create reverts and keeps the error', …)               // requesting null, lastError equals error.message
test('session.updated to ended moves it to lastEnded and recent', …) // session null, lastEnded set, recent contains it, sorted newest first, max 6
test('socket.closed keeps the session', …)                           // socket 'reconnecting', session unchanged, requesting cleared, temps kept
test('ui.message adds a toast with a level', …)                      // 'warning' maps to 'warn'
```

- [ ] **Step 2: Run them to verify they fail**

Run (inside a node container on vm2, since the workstation has no Node): `ssh vm2 'cd ~/Live-FPGA-Lab/src/frontend && docker run --rm -v "$PWD":/w -w /w node:24-bookworm-slim node --test --experimental-strip-types "src/**/*.test.ts"'` after `scripts/deploy-vm2.sh --no-build`.
Expected: FAIL, "Cannot find module … reducer.ts".

- [ ] **Step 3: Implement `types.ts`, `copy.ts` and `reduce()`** with the signatures above. `start.requested` is ignored while `requesting` is set or `session` is live. `session.updated` with status `ended` for the user's own session moves it to `lastEnded` and merges into `recent` (same `mergeSession` logic as today's `main.tsx`, newest first, six kept). `socket.closed` sets `socket: 'reconnecting'` and clears `requesting` only.

- [ ] **Step 4: Run the reducer tests to verify they pass** (same command). Expected: all PASS.

- [ ] **Step 5: Write the failing derive tests** in `derive.test.ts`:

```ts
test('phase follows the session and board', …)   // connecting when !ready; project when board.mode==='project'; fault when status fault/offline or faults non-empty; busy when another visitor is active and no own session; requesting; queued; starting; active; ending; ended when lastEnded set and no session; else idle
test('timeLeft appears when expires_at is set later', …) // null → 252 when expires_at is now+252s
test('queueSentence and ordinal', …)             // position 2 of length 3 → "2nd of 3 waiting"; 1 → "1st"; 11 → "11th"; 22 → "22nd"
test('duration formats minutes and seconds', …)  // 270 → "4m 30s"; 45 → "45s"; 0 → "0s"
test('readAgo counts from the last sample', …)   // no samples → null; sample 2.4 s ago → 2
test('sparkPath is empty with fewer than two samples and never contains NaN', …)
test('demoKind picks the interactive view for n-body only', …)
test('recentOutcome words and tones', …)         // user_ended → "Ended by the visitor" ok; expired → "Time ran out while others were waiting" neutral; cancelled → "Left the queue" neutral; programming_failed → "Programming failed" bad; fpga_fault → "Stopped by a board fault" bad; board_offline → "Board went offline" bad; board_reserved → "Board needed for GPGPU testing" neutral; timed_out → "Dropped after the visitor left" neutral
```

- [ ] **Step 6: Run them to verify they fail.** Expected: FAIL on missing module.

- [ ] **Step 7: Implement `derive.ts`** with the signatures above. `sparkPath` maps samples to `M x y L x y …` in a `width × height` box with 4 px vertical padding, flat line at mid-height when all values are equal.

- [ ] **Step 8: Run all frontend tests to verify they pass** (same command, now including `autostart.test.ts`). Expected: all PASS.

- [ ] **Step 9: Commit** (only if Jason has said to commit)

```bash
git add src/frontend/src/lab src/frontend/package.json
git commit -m "feat(frontend): pure lab state reducer and derivations with tests"
```

---

### Task 3: App shell: socket hook, top bar, trace, layout, skeleton

**Files:**
- Create: `src/frontend/src/lab/socket.ts`, `src/frontend/src/App.tsx`, `src/frontend/src/components/TopBar.tsx`, `src/frontend/src/components/Led.tsx`, `src/frontend/src/components/Trace.tsx`, `src/frontend/src/components/Skeleton.tsx`, `src/frontend/src/components/Toasts.tsx`, `src/frontend/src/components/BoardPanel.tsx` (band, identity, sentence; readouts come in Task 4), `src/frontend/src/components/SessionPanel.tsx` (connecting skeleton only for now), `src/frontend/src/components/DemoList.tsx` (skeleton rows only for now), `src/frontend/src/components/RecentSessions.tsx` (skeleton rows only for now)
- Create: `src/frontend/src/dev/fixtures.ts` (the mock's example states as `LabState` objects, keyed `idle | busy | arrival | queued | starting | active | ending | project | fault | offline | connecting`)
- Rewrite: `src/frontend/src/main.tsx` (mount only), `src/frontend/src/styles.css` (ported from `docs/superpowers/mocks/lab/lab.css` minus tokens, minus `.mockbar`)
- Modify: `docker-compose.yml` web-api `build.args: VITE_MOCK_STATES: ${VITE_MOCK_STATES:-0}`; `docker/web-api.Dockerfile` `ARG VITE_MOCK_STATES=0` and `ENV VITE_MOCK_STATES=$VITE_MOCK_STATES` before the build step

**Interfaces:**
- Consumes: `reduce`, `initialState`, `LabState`, `phase`, `pillText` from Task 2.
- Produces: `useLabSocket(dispatch: Dispatch<WsEvent | LocalAction>): { send(type: string, payload?: Record<string, unknown>): string }` (returns the `request_id`; reconnect with the same backoff as today, max 2 s; opens `/api/ws` with subprotocol `fpga-demo.v1`).
- Produces: `App` renders, in order inside `<div class="wrap" data-trace>`: `<TopBar>`, `<main>`, `<section class="hero" id="session-hero">` with `<BoardPanel>` and `<SessionPanel>` (or `<Stage>` from Task 6), `<section class="sec" id="demos">`, `<section class="sec" id="recent">`, footer. Section headings carry `data-pad`. The band carries `data-pad`.
- Produces: `Trace` props `{ online: boolean }`; it draws exactly as the mock's `lab.js` trace (entry from `y = -40`, stub into the first pad, vias and stubs at the others, reveal classes `lit` on sections, 78 % viewport target, 0.12 easing, pulse 44 px at 0.52 px/ms only when `online`), using an `IntersectionObserver` fallback (`threshold: 0.3`) instead of per-frame `getBoundingClientRect` for the "switch on anyway" rule.
- Produces: `?mock=<fixture>` replaces the socket with the fixture when `import.meta.env.VITE_MOCK_STATES === '1'`; otherwise the parameter is ignored.

- [ ] **Step 1: Write `socket.ts`** as a hook around the connection code in today's `main.tsx` (lines 90–140), dispatching `socket.opened`, every parsed server message as a `WsEvent`, and `socket.closed`.

- [ ] **Step 2: Write `App.tsx`** with `useReducer(reduce, initialState)`, a one-second `tick` dispatch, `useLabSocket`, and the layout above. Phase `connecting` renders `Skeleton` variants: board identity (title bar 46 %, line 38 %), one sentence bar, three readout blocks 120 px, session (headline bar 62 %, two lines, button pill 160×44), four demo rows (thumb, title 55 %, line, tag) and three recent rows, all `aria-hidden`.

- [ ] **Step 3: Write `TopBar.tsx`**: name link to `https://njason.dev`, nav "Session", "Demos", "Recent" (`href="#session-hero"`, `#demos`, `#recent`), board pill (`Led`, board name from `board.device_name` or "Board", `pillText`). The pill mirrors the session when a `#session-hero` IntersectionObserver reports it off screen and the visitor has a session (`pillText(state, false)`), and its `href` is then `#session-hero`.

- [ ] **Step 4: Port `styles.css`** from the mock, renaming nothing except dropping `.mockbar`; add `.fallback` styles for the no-JS copy (hidden once React mounts).

- [ ] **Step 5: Write `fixtures.ts`** and the `?mock=` switch in `App.tsx` (when enabled, `dispatch({ type: 'state.initial', …fixture })` once and skip the socket).

- [ ] **Step 6: Deploy with mock states on**

Run: `VITE_MOCK_STATES=1 scripts/deploy-vm2.sh` (the variable must reach `docker compose build`; add `VITE_MOCK_STATES=1` to vm2's `.env` for the overhaul period instead if the shell variable does not propagate).
Expected: build passes including `npm test`; `https://fpga.njason.dev/?mock=connecting` shows the skeleton; `?mock=idle` shows the shell with the trace landing on the band.

- [ ] **Step 7: Screenshot and review** from the workstation with headless Chrome at 1440 and 390 px for `?mock=connecting` and `?mock=idle` (same command pattern as the mock screenshots, against the live URL). Expected: matches the mock's connecting and idle states apart from readouts, rows and recent (next tasks); no horizontal overflow.

- [ ] **Step 8: Commit** (only if Jason has said to commit)

```bash
git add src/frontend docker docker-compose.yml
git commit -m "feat(frontend): app shell in the circuit-board world with trace, top bar and skeleton"
```

---

### Task 4: Board readouts, demo rows and thumbnails

**Files:**
- Create: `src/frontend/src/components/Sparkline.tsx`, `src/frontend/src/components/DemoRow.tsx`, `src/frontend/src/components/DemoThumb.tsx` (drawn fallback: the mock's generic placeholder, a raised tile with a cyan dot at the trace end)
- Modify: `src/frontend/src/components/BoardPanel.tsx` (three readouts), `src/frontend/src/components/DemoList.tsx`
- Modify: `src/web_api/demo_loader.py` (`thumbnail: Path | None` on `DemoDefinition`, read with `_optional_path(raw, "thumbnail", root)`), `src/web_api/board.py` (`_public_demo` adds `"thumbnail_url": f"/api/demos/{demo.id}/thumbnail"` when `demo.thumbnail` is a file, else `None`), `src/web_api/api.py` (`GET /api/demos/{demo_id}/thumbnail` → `FileResponse` with `Cache-Control: public, max-age=86400`, 404 when unknown or missing)
- Create: `tests/test_demo_thumbnail.py`
- Create: `demos/01-gpgpu-nbody/thumbnail.svg`, `demos/02-dvd-logo-video/thumbnail.svg`, `demos/03-gpgpu-ripple/thumbnail.svg`, `demos/04-gpgpu-triangle/thumbnail.svg` (the four drawings from `docs/superpowers/mocks/lab/lab.js`, 120×76 viewBox), plus `thumbnail.svg` for the four untracked demos on vm2 (`05-gpgpu-metaballs`, `06-gpgpu-julia`, `07-gpgpu-cube`, `08-gpgpu-mandelbrot`) synced by a one-off `scp`, and `"thumbnail": "thumbnail.svg"` added to each `DEMO_DEFINITION` (the four in the repo in git, the four on vm2 by `sed` over ssh)

**Interfaces:**
- Consumes: `boardStatus`, `readAgo`, `sparkPath`, `demoKind` from Task 2; `Demo.thumbnail_url`.
- Produces: `DemoRow` props `{ demo: Demo; state: 'start' | 'starting' | 'queued' | 'running' | 'busy' | 'blocked'; note: string | null; chosen: boolean; onStart(): void }`. Button labels: start → "Start" (cyan), starting → "Starting…", queued → "In your queue", running → "Running", busy → "Start" (cyan, note "Joins the queue"), blocked → "Start" disabled with the note from `copy`.
- Produces: `GET /api/demos/{id}/thumbnail` and `demos[].thumbnail_url` in `state.initial`.

- [ ] **Step 1: Write the failing backend test** `tests/test_demo_thumbnail.py`:

```python
def test_loader_reads_thumbnail_path(tmp_path): …          # DEMO_DEFINITION with "thumbnail": "thumbnail.svg" → DemoDefinition.thumbnail == tmp_path/"x"/"thumbnail.svg"
def test_public_demo_includes_thumbnail_url_only_when_file_exists(): …  # BoardManager._public_demo → "thumbnail_url" is "/api/demos/<id>/thumbnail" or None
def test_thumbnail_endpoint_serves_file_and_404s(): …       # TestClient like tests/test_public_board.py: 200 with image/svg+xml and Cache-Control public, max-age=86400; 404 for unknown id
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest tests/test_demo_thumbnail.py -v` (first time; later just the pytest line)
Expected: FAIL, `DemoDefinition` has no field `thumbnail`.

- [ ] **Step 3: Implement the loader field, `_public_demo` and the route** as specified in Files.

- [ ] **Step 4: Run the whole backend suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Write the eight `thumbnail.svg` files** (extract the eight SVG strings from the mock's `T` map, each wrapped as a standalone `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 76">`), add `"thumbnail": "thumbnail.svg"` to the four repo definitions, and copy the other four plus their `sed` edit to vm2.

- [ ] **Step 6: Implement `Sparkline`, the three readouts in `BoardPanel`, `DemoThumb`, `DemoRow` and `DemoList`.** Readouts: Status (`boardStatus`), Temperature (`°C` with one decimal, sparkline 34 px tall, "Die, read N s ago" or "No reading"), Queue ("Empty"/"N waiting", detail "Nobody waiting"/"One visitor after the current one"/"Visitors after the current one"). Rows in `DemoList` get their `state` from `phase` and the session: own chosen demo → starting/queued/running by status; any live own session → others `blocked` with "One session at a time"; another visitor active → `busy`; project → `blocked` "In use for GPGPU testing"; fault/offline/connecting → `blocked` "Until the board recovers"/"Unavailable".

- [ ] **Step 7: Deploy and review**

Run: `scripts/deploy-vm2.sh`, then `curl -s https://fpga.njason.dev/api/demos/gpgpu-nbody/thumbnail | head -c 60` (starts with `<svg`), screenshots of `?mock=idle`, `?mock=busy`, `?mock=project` at 1440 and 390 px and of the real page (board in project mode today).
Expected: eight rows with thumbnails from the server, two columns at 1440 px, readouts never truncate, the real page shows "In use for GPGPU testing" with live temperature.

- [ ] **Step 8: Commit** (only if Jason has said to commit)

```bash
git add src/web_api src/frontend demos/*/thumbnail.svg demos/*/demo_definition.py tests/test_demo_thumbnail.py
git commit -m "feat: board readouts, demo rows and per-demo thumbnails"
```

---

### Task 5: Session panel and the start flow

**Files:**
- Modify: `src/frontend/src/components/SessionPanel.tsx`, `src/frontend/src/App.tsx` (start/end/cancel handlers, autostart wiring, scroll-into-view), `src/frontend/src/components/TopBar.tsx` (session mirror already wired in Task 3; verify)
- Create: `src/frontend/src/components/PhaseSwap.tsx` (keyed cross-fade: old child fades out, new child rises 16 px in 300 ms; a plain swap under reduced motion)
- Create: `src/frontend/checks/check.py` (Python Playwright; `python3 -m venv .venv-checks && .venv-checks/bin/pip install playwright && .venv-checks/bin/playwright install chromium`)

**Interfaces:**
- Consumes: `send` from Task 3; `phase`, `queueSentence`, `queueEta`, `timeLeft`, `duration`, `endedSentence` from Task 2; `autostart`/`withoutStart` unchanged.
- Produces: `SessionPanel` props `{ state: LabState; now: number; onStart(demoId: string): void; onCancel(): void; onEnd(): void }` rendering, by phase: idle "The board is free" + "Choose a demo" (`href="#demos"`); busy "Someone is on the board" + sentence with the running demo and queue length; requesting LED blink + "Requesting the board for <demo>"; queued headline `queueSentence`, "For <demo>", "Estimated start in <duration>" or the no-estimate sentence, flat bar (`width = 100 − eta / (position × 300) × 100` clamped), "Leave the queue"; starting LED blink + "Programming the board for <demo>" + "Cancel"; ending "Ending" + resetting sentence; ended `endedSentence` + "Start again" (`href="#demos"`); project, fault, offline as in the spec table. The `lastError` sentence shows under the headline in amber until the next action.
- Produces, in `App`: `onStart(demoId)` dispatches `start.requested` with the `request_id` returned by `send('session.create', { demo_id })`, then on phones (`matchMedia('(max-width: 760px)')`) calls `scrollIntoView({ block: 'start', behavior })` on `#session-hero`; `onCancel` and `onEnd` both send `session.end` with the session id and dispatch `end.requested`.

- [ ] **Step 1: Implement `PhaseSwap` and `SessionPanel`** per the Interfaces, using `copy.ts` only.

- [ ] **Step 2: Wire `App`**: handlers, the arrival note (`document.referrer` host `njason.dev` → "Opened from njason.dev", any other non-empty referrer → "Opened from a link", none → no note), `autostart` as today but calling `onStart`.

- [ ] **Step 3: Write `src/frontend/checks/check.py`** using Playwright's sync API against `https://fpga.njason.dev`: for each width in `[360, 390, 768, 1100, 1440]` and each fixture in `[connecting, idle, busy, queued, starting, active, ending, project, fault, offline]`: load `/?mock=<fixture>`, wait for `networkidle`, assert `document.documentElement.scrollWidth <= window.innerWidth`, assert no console errors, assert the trace `svg.trace` left edge plus 18.5 px is at least 28 px left of the `main` content edge, screenshot to `src/frontend/checks/out/<fixture>-<width>.png`. Then a flow check on `?mock=idle`: click the first "Start" button, assert within 100 ms that the session panel headline contains "Requesting the board", click the second row's Start and assert it is disabled; `double click sends one request` by counting `start.requested` through a `window.__labDispatches` array that `App` fills only when `VITE_MOCK_STATES === '1'`.

- [ ] **Step 4: Deploy and run the checks**

Run: `VITE_MOCK_STATES=1 scripts/deploy-vm2.sh && .venv-checks/bin/python src/frontend/checks/check.py`
Expected: exit 0, screenshots written; review them against the mock.

- [ ] **Step 5: Real-board check** (needs the board in demo mode, Jason flips it): open https://fpga.njason.dev, press Start on DVD Logo HDMI, confirm in order: button reads "Starting…" at once, panel "Requesting the board", then "Programming the board for DVD Logo HDMI" with a blinking LED, then the stage (Task 6) or, before Task 6, the panel "Running"; press End and confirm "Ending" then "Your DVD Logo HDMI session ended".

- [ ] **Step 6: Commit** (only if Jason has said to commit)

```bash
git add src/frontend
git commit -m "feat(frontend): session panel with instant start feedback and browser checks"
```

---

### Task 6: Stage, ending and recent sessions

**Files:**
- Create: `src/frontend/src/components/Stage.tsx`
- Modify: `src/frontend/src/App.tsx` (phase `active` renders `Stage` first in the hero at full width and `BoardPanel` compact after it; scroll to `#session-hero` top on the transition into `active`), `src/frontend/src/components/RecentSessions.tsx`, `src/frontend/src/components/BoardPanel.tsx` (`compact` prop)

**Interfaces:**
- Consumes: `timeLeft`, `duration`, `recentOutcome` from Task 2.
- Produces: `Stage` props `{ session: Session; demoName: string; timeLeft: number | null; onEnd(): void }`: bar with `Led`, demo name, "<duration> left, someone is waiting" when `timeLeft` is not null, buttons "Fullscreen" (`iframe.requestFullscreen()`), "Open in a new tab" (`window.open(demo_url, '_blank', 'noopener,noreferrer')`), "End session" (silk primary); the iframe (`title` "<demoName> demo", `src = demo_url`, `allow="fullscreen"`) behind a raised "Loading the demo" block until its `load` event; minimum height `calc(100vh - 62px - 40px)` (phone `- 56px - 24px`). The iframe stays mounted while `socket` is `reconnecting`.
- Produces: `RecentSessions` rows: dot tone from `recentOutcome`, demo name, outcome text, time formatted as today's `formatRecentSessionTime` but written "Today 14:02" / "16 Nov 13:41". Filter with today's `wasOnBoard`. Empty: "No sessions yet today." in a panel.

- [ ] **Step 1: Implement `Stage`, the active layout in `App`, `BoardPanel` compact mode and `RecentSessions`.**

- [ ] **Step 2: Deploy and review** `?mock=active` and `?mock=ending` at 1440 and 390 px, plus the real flow from Task 5 Step 5 now ending in the stage with the live demo page inside. Expected: the stage is the first thing on screen after Start, time left appears only when someone queues, Fullscreen works, End returns to the panel with the ended sentence and the recent list shows the session.

- [ ] **Step 3: Run `src/frontend/checks/check.py` again.** Expected: exit 0.

- [ ] **Step 4: Commit** (only if Jason has said to commit)

```bash
git add src/frontend
git commit -m "feat(frontend): active session stage and recent sessions"
```

---

### Task 7: Embedded demo pages in the same world

**Files:**
- Modify: `demos/01-gpgpu-nbody/demo/interactive_3d.py` (the `HTML` string's `<head>` and `<style>` only), `demos/02-dvd-logo-video/video_stream.py` (its page style), `src/web_api/video.py` (`render_video_page` style)

**Interfaces:**
- Consumes: `/static/tokens.css` from Task 1 (absolute URL; valid inside the session proxy iframe, in a new tab and on `/video` because all share the lab's origin).
- Produces: all three pages link `/static/tokens.css`, use `var(--font-text)` for text and `var(--font-display)` for the n-body metrics' values, panels `var(--panel)`, controls `var(--raised)` with `var(--hover)` on hover, the one live action (Play/Pause; the transport selector's current choice) in cyan with ink text, labels `var(--dim)`, no borders or shadows, the n-body `scene.background` set to `0x0b1d21`, and the capture page's status dot `var(--led)` when a signal is present and `var(--dim)` otherwise.

- [ ] **Step 1: Restyle the three style blocks** as above, keeping every id, class and layout rule the scripts depend on (`#view`, `aside`, `.metric`, `.overlay`, `.switch`, `body.has-signal`).

- [ ] **Step 2: Render each page to a file and screenshot it** (Python: import or exec the module to get the HTML string, write to the scratchpad, open with headless Chrome at 1440 and 390 px). Expected: same palette and fonts as the lab, controls readable, nothing overlapping.

- [ ] **Step 3: Deploy** (`scripts/deploy-vm2.sh`; the demo files are read from the mounted `demos/` folder, the `/video` page from the image) and, with the board in demo mode, open the n-body demo for real inside the stage. Expected: the iframe content no longer looks like a different app.

- [ ] **Step 4: Commit** (only if Jason has said to commit)

```bash
git add demos/01-gpgpu-nbody/demo/interactive_3d.py demos/02-dvd-logo-video/video_stream.py src/web_api/video.py
git commit -m "style(demos): embedded demo pages use the lab's tokens and fonts"
```

---

### Task 8: Polish, accessibility, docs

**Files:**
- Modify: `src/frontend/src/styles.css`, `src/frontend/src/components/*.tsx` as the review requires, `README.md` (frontend section: tokens file, fonts, `?mock=` flag, `scripts/deploy-vm2.sh`, thumbnails in "Adding a demo"), `docs/superpowers/specs/2026-11-17-frontend-redesign-design.md` (status line → implemented, date)
- Delete: nothing in `demos/`; old CSS rules that no component uses

**Interfaces:** none new.

- [ ] **Step 1: Keyboard and reduced-motion pass**: tab through the idle page and the stage (focus ring visible on every control, order follows the DOM), load with `prefers-reduced-motion: reduce` emulated in `check.py` (`page.emulate_media(reduced_motion='reduce')`): trace fully drawn, pads lit, no pulse, no breathing, sections visible.

- [ ] **Step 2: Contrast sample** in `check.py`: read computed colours of the readout labels, the dim lead, the tag text and the cyan button text and assert WCAG AA (4.5:1) with a small contrast function. Fix any failure by moving to the next lighter token, never by adding a shadow or border.

- [ ] **Step 3: Final screenshots** of every fixture at 390 and 1440 px into `docs/superpowers/mocks/lab/final/` for Jason, and remove `VITE_MOCK_STATES=1` from vm2's `.env`, then `scripts/deploy-vm2.sh` once more. Expected: `?mock=idle` on the live site shows the real board, not the fixture.

- [ ] **Step 4: Update `README.md`** and the spec status line.

- [ ] **Step 5: Commit** (only if Jason has said to commit)

```bash
git add -A src/frontend README.md docs
git commit -m "chore(frontend): polish, accessibility checks and docs for the redesign"
```

---

### Task 9 (portfolio side, separate repo): refresh the lab card

Not in this repo. After Task 8, take a 1600×1000 screenshot of the idle lab for the portfolio's Live FPGA Lab card (`lab.jpg` in its media) and hand it to Jason with a note; the portfolio build is his.
