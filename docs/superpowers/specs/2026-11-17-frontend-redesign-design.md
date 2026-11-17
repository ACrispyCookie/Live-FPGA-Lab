# Live FPGA Lab frontend redesign

Status: draft for Jason's approval (2026-11-17). Decisions marked **(Jason)** are his; everything else is the builder's call and can be corrected.

## Intent

The lab at https://fpga.njason.dev is reached from the portfolio at https://njason.dev, whose world is "one dark circuit board; the live lab widget is the powered part; a copper trace carries the current into the work". The portfolio's spec deliberately keeps that widget compact and says the meters, the temperature chart and the demo list "live on the lab itself". The lab should therefore read as the place the trace arrives: the same board, seen up close.

Today the lab uses Inter, indigo gradients, glass panels, glows and ALL-CAPS eyebrows, which is the exact look the portfolio's taste rules forbid, and its three embedded demo pages each use a different palette again.

## Goals

- A visitor coming from njason.dev feels they are still on the same site: same tokens, type, shapes, trace and LED vocabulary, and a top bar that mirrors the portfolio's.
- The board, the demos and the visitor's own session are readable at a glance, on a phone and on a desktop.
- Every state has honest copy: connecting, idle, queued, starting, active, ending, fault, offline, and "in use for GPGPU testing" (the board's `project` mode).
- The demo list scales to a dozen demos (eight are live now).
- The embedded demo pages (n-body side panel, HDMI viewer, `/video`) use the same tokens and fonts. **(Jason)**

## Non-goals

- Changing the backend's session, queue or WebSocket behaviour. The only backend additions are an optional per-demo thumbnail and nothing else.
- A light theme. The portfolio is dark only.
- Sharing code with the portfolio repo. Tokens are copied with a note pointing at the portfolio's `docs/DESIGN_SYSTEM.md`.

## Anti-goals

- Anything on the portfolio's avoid list: gradients, glass, glows, borders or hairlines at rest, eyebrow or ALL-CAPS labels, "→" on links, middle-dot meta strings, violet, generic fade-up on every section.
- A KPI dashboard of big numbers. Readouts carry units and conditions, like an instrument.
- Fake or invented live values anywhere.

## Constraints

- Vite + React SPA built into `src/web_api/static/` with `base: '/static/'`; the Docker image builds it. Keep `autostart.ts` and its tests.
- The frontend gets everything from `/api/ws` (`state.initial`, `board.updated`, `queue.updated`, `session.updated`, `recent_sessions.updated`, `ui.message`). Temperature history is not stored server side; the client keeps the last few minutes of `board.updated` samples for the sparkline.
- Production (vm2, `~/Live-FPGA-Lab`) is on the same commit as `origin/main`; the four extra demos are untracked folders there (`05-gpgpu-metaballs` to `08-gpgpu-mandelbrot`).
- This workstation has no Node, Docker, uv or passwordless sudo. The build and deploy happen on vm2 **(Jason)**: files are synced from this checkout to `vm2:~/Live-FPGA-Lab`, then `docker compose build web-api && docker compose up -d web-api` there (the Dockerfile builds the frontend in a Node stage). vm2 has 1 CPU and about 1 GB of RAM, so builds are slow and are batched per milestone. There are no visitors yet, so a broken deploy is acceptable **(Jason)**. Screenshots are taken from this workstation against https://fpga.njason.dev with headless Chrome.
- The dev server has no WebSocket proxy and the web API refuses to start without a board, so component states are exercised through a `?mock=<state>` switch in development builds only (stripped from production), replaying fixture states through the same reducer the socket feeds.

## Approaches considered

1. **Keep Vite + React, rewrite the UI layer.** Split `main.tsx` into components, add `tokens.css`, self-host the two fonts with Fontsource, keep the socket and autostart code. Chosen: lowest risk, keeps tests.
2. **Rebuild in Astro like the portfolio.** Rejected: the lab is a live app with one long-lived socket; islands gain nothing.
3. **A shared token package.** Rejected for now: the portfolio source is not public and the two deploy separately. A copied token file with a sync note is enough.

## Decisions (Jason, 2026-11-17)

1. Production code lives on vm2; it matches `origin/main` plus untracked demo folders.
2. Demos are rows with a small thumbnail each. **(Jason)**
3. The active session is a stage inside the page if it clearly commands attention; the old take-over-the-page behaviour is the fallback. **(Jason)** Builder's reading: the stage takes the hero slot at full width and viewport height and the page scrolls to it, so it is the first and only thing on screen without hiding the rest. A Fullscreen button remains.
4. The embedded demo pages are restyled too. **(Jason)**
5. The lab's top bar links the name back to njason.dev. **(Jason)**

## Visual plan

### Tokens (copied from the portfolio)

Ground `#0b1d21`, panel `#11282d`, raised `#183539`, hover `#1f4248`, lift `#28525a`; text `#eaf2f1`, secondary `#9db6b8`; groove `#183539`, copper `#3b7a82`; cyan `#41e2f2` with ink `#05252a` on it; gold `#d8b46a` with ring `#a8873f`; LED `#5dffa8`; amber `#f0a64a` for fault wording; fault red `#ff6b5e` for failed outcomes only.

Depth from the mask shades only. No borders, shadows, glows, gradients or blur at rest. Pill buttons: live/primary cyan with ink text, secondary raised with silk text, disabled raised with dim text. Panels 22 to 28 px radius, tiles 16 px.

### Type

Bricolage Grotesque for display (board name, section headings, readout numbers, demo names), Hanken Grotesk for text, tabular numerals. Five sizes: title `clamp(1.9rem, 3.2vw, 2.6rem)`, lead `1.3rem`, body `1.0625rem` at line-height 1.6, small `.875rem`, and the readout number at `1.3rem` display. Nothing under 13 px. Paragraphs capped at 65ch. Sentence case everywhere, no eyebrows.

### Layout

Content max 1200 px, one left content edge, a trace gutter to its left (68 px with the trace at 18.5 px; on phones 42 px and 11 px). Page gutters 20 px, 12/16 px on phones, with safe-area insets.

```
Jason Nikas                      Demos  Session  Recent        [● Smart Zynq SL  Idle]
  │ trace enters from the top edge, pulse running
  ●─┌ ● Live FPGA Lab ───────────────── ○○○○ ┐ ┌ Your session ──────────────┐
    │ Smart Zynq SL                           │ │ Nothing running.            │
    │ Xilinx xc7z020, on the bench at home    │ │ Pick a demo below; if the   │
    │ One real board, one visitor at a time.  │ │ board is free it is          │
    │ [Idle] [61.9 °C ▁▂▃▂] [0 waiting] [–]   │ │ programmed for you.          │
    └─────────────────────────────────────────┘ └─────────────────────────────┘
  ● Demos
  │ [thumb] GPGPU n-body simulator   Interactive 3D view        Start
  │ [thumb] DVD Logo HDMI            Live HDMI capture          Start
  │ … eight rows, same anatomy
  ● Recent sessions
  │ ● GPGPU n-body simulator     Ended by the visitor     14:02
```

- **Top bar**: solid ground colour, no blur. Left: "Jason Nikas", a link to https://njason.dev. Middle: Session, Demos, Recent, in page order (hidden on phones). While the session panel is off screen and the visitor has a session, the right-hand pill shows that session instead of the board ("2nd in line, 4m 30s", "Programming", "Running, 4m 12s left") and links to it. Right: the board pill with the LED, board name and status word, the mirror of the portfolio's "Live FPGA Lab" pill.
- **Board panel** (the component the trace lands on): the portfolio widget's flat cyan band with LED, "Live FPGA Lab" and four gold pins, then the board name, part and location line, one sentence on the one-board rule, and four raised readout tiles: Status, Temperature (value plus a sparkline of the last minutes and "read N s ago"), Queue, Running now. Numbers in display type with units.
- **Session panel**: the visitor's own state. Idle: an invitation. Queued: place ("2nd of 3 waiting"), estimated start as a countdown, a flat cyan progress bar, the chosen demo, "Leave the queue". Starting: "Programming the board for GPGPU n-body" with the LED blinking. Ending: "Resetting the board for the next visitor". Arrival through `?start=`: the chosen demo row is highlighted and the panel says "Starting GPGPU n-body, opened from njason.dev" when the referrer is the portfolio, otherwise "opened from a link".
- **Stage** (active): replaces the hero at full width, min-height viewport minus the bar. A slim raised bar: LED and demo name, time left when contended, Fullscreen, Open in new tab, End session. The iframe fills the rest. The board panel moves below the stage in compact form; demo rows show "In use by you".
- **Demo rows**: thumbnail 120×76 (88×56 on phones), name in display type, one line of description, a tag saying what the visitor will see ("Interactive 3D view" or "Live HDMI capture"), and the Start button. Disabled states read "Busy", "In your queue" or "In use for GPGPU testing".
- **Recent sessions**: rows with a filled status dot (LED green for ended normally, copper for cancelled or expired, fault red for failures), demo name, outcome in words, and the time, no middle dots.
- **Footer**: one line: "Part of njason.dev" and "Source on GitHub".

### States and copy

| State | Board pill | Session panel |
|---|---|---|
| connecting | grey LED, "Connecting" | skeleton: raised shimmering blocks in the shape of the real content (board name, sentence, three tiles, session headline and button, four demo rows, three recent rows), no placeholder text **(Jason)** |
| idle | green LED, Idle | invitation |
| project mode | green LED, "In use for GPGPU testing" | "The board is in use for GPGPU testing right now. Demos reopen when it is free." Start buttons disabled |
| queued | green LED, Running: demo | place, ETA countdown, bar, Leave the queue |
| starting | green LED, Programming | "Programming the board for <demo>" |
| active | green LED, Running: demo | stage |
| ending | green LED, Resetting | "Resetting the board for the next visitor" |
| fault | grey LED, amber "Fault" | "The board reported a fault: <type>. It recovers on its own; demos reopen when it does." |
| offline / socket lost | grey LED, "Offline" or "Reconnecting" | "Status unavailable" |

### Interaction flow (Jason: every step must be instant, clean and unmistakable)

The visitor must never wonder what just happened or what happens next. Rules:

1. **Pressing Start answers within one frame.** The button itself turns into "Starting…" with the LED blink, every other Start button dims with the note "One session at a time", and the session panel switches to "Requesting the board for <demo>" before the server replies. If `command.result` comes back with an error, the row and panel revert and the error is shown inline in the session panel in plain words, not only as a toast.
2. **The session panel is the single source of truth for the visitor**, and it is always reachable: on desktop it sits in the hero; on phones, after pressing Start the page scrolls the session panel into view, and while it is off screen the top-bar pill mirrors it (place, countdown or "Running") and tapping the pill scrolls back to it.
3. **Each transition is visible.** queued → starting → active → ending each change the panel's headline, and the change animates (old content fades and the new rises 16 px, 300 ms, transform and opacity only). The LED blinks only while programming. Countdowns tick every second in tabular numerals so nothing jumps.
4. **The demo appears where the visitor is looking.** When the session becomes active the stage replaces the hero and the page scrolls to its top; the stage bar shows the demo name, the time left when somebody is waiting, and the three actions. The iframe shows a raised "Loading the demo" block until its first load event. Fullscreen and "Open in a new tab" are always visible, never hidden in a menu.
5. **Ending is explained, not just done.** "End session" asks nothing (restarting is cheap) but the panel immediately reads "Ending, the board is resetting for the next visitor" and then "Your <demo> session ended" with a Start-again link. Sessions ended by the server (time ran out, fault, programming failed) say so in the same place in one sentence, with what to do next.
6. **Queue position is a sentence, not a number.** "2nd of 3 waiting, estimated start in 4m 30s" plus the flat bar; when the estimate is unknown the panel says why ("The current visitor has no time limit until someone waits; you are next").
7. **Toasts are for the unexpected only** (server messages, reconnects). Normal flow never relies on a toast.
8. **Reconnects keep the visitor's place.** Losing the socket shows "Reconnecting" in the pill and panel without clearing the session; the stage keeps the iframe mounted.
9. **Arrival by link** (`?start=`) behaves exactly like pressing Start, with the row highlighted and the panel noting where the visitor came from.

### Motion

One orchestrated moment: on load the trace draws in from the top edge and lands on the board panel, and the LED switches on when the socket connects (power-on). The pulse runs while connected. Sections switch on as the trace reaches their pad (opacity and 16 px rise, 450 ms, children staggered 70 ms) with a 70 %-of-viewport fallback. The LED breathes while online. Transform and opacity only. Under reduced motion: trace fully drawn, pads lit, no pulse, no breathing, no rise. Without JavaScript the app cannot run anyway; the static `index.html` shows the board panel's static copy and "Connecting".

### Embedded demo pages

The n-body side panel, the HDMI viewer and `/video` load `/static/tokens.css` and the self-hosted fonts from the lab's static folder and swap their palettes for the tokens: raised controls, cyan for the one live action, dim labels, Hanken for text and Bricolage for the metric numbers. Layouts stay as they are.

## Data needed from the backend

- Optional `thumbnail` path in `DEMO_DEFINITION`, served at `GET /api/demos/{id}/thumbnail` (SVG or PNG, cache-friendly). Demos without one get a drawn placeholder in the palette.
- Nothing else. The public endpoints stay as they are.

## Left to the builder

- Exact component split and file layout under `src/frontend/src/`.
- The sparkline's window (about five minutes at the board's update cadence) and sample cap.
- Whether the mock socket server records real sessions from vm2 or uses hand-written fixtures.
- Thumbnail artwork for the eight current demos: a capture frame where the demo has HDMI output, a drawn diagram otherwise.

## Acceptance

- Screenshots at 1440 and 390 px of every state in the table above, reviewed before each milestone.
- Browser checks in `src/frontend/checks/check.py` (Python Playwright, run from this workstation against the deployed lab) passing: no horizontal overflow at 360, 390, 768, 1100 and 1440 px, no console errors, every state renders, the trace stays at least 28 px clear of content, a real click on Start changes the session panel within one frame. The portfolio's taste linter needs Node and is not run here; its rules are applied by hand in the review screenshots.
- No horizontal overflow at 360 to 1440 px, keyboard focus visible, reduced motion honoured, WCAG AA contrast on rendered pages.
- `npm test` (autostart) and `pytest` still pass.

## Phases

1. Throwaway styled mock in `docs/superpowers/mocks/lab/` with switchable states, screenshots, Jason's approval of the direction.
2. Foundation: tokens, fonts, reset, top bar, trace, layout grid, dev mock socket server.
3. Board panel, demo rows, thumbnails endpoint, non-session states.
4. Session panel, stage, ending, recent sessions.
5. Embedded demo pages.
6. Polish, checks, screenshots, README update.
7. Portfolio follow-up: replace the old dashboard screenshot on the lab card.
