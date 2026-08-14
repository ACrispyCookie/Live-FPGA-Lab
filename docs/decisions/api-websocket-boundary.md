# FPGA Demo API Boundary: Project Sessions, Leases, REST, and WebSocket

## Final Decision

There is no public split between `projects` and `demos`.

The user-facing object is a **project**. Some projects are runnable on the FPGA platform and can be leased as a time-limited **session**. Non-runnable projects still appear in the catalog as source/portfolio entries, but they cannot be requested for FPGA access.

The public API is therefore:

```text
Projects = what users can choose from
Sessions = time-limited exclusive access to the FPGA for a runnable project
REST = snapshots, session create/release/extend, artifact downloads
WebSocket = live session/queue/board/thermal/log events
Internal actions/jobs = private implementation details
```

No public `/api/demos` endpoint.

---

## Why Projects and Demos Are Not Separate Public APIs

A separate `/api/projects` + `/api/demos` split leaks implementation detail and makes the UI confusing:

- users select projects, not internal demo definitions;
- a project can expose a runnable capability directly;
- the API should not require frontend code to join project records to demo records;
- fake “coming soon” demos were a symptom of this bad split.

Final model:

```json
{
  "id": "ece338-gpgpu-nbody-3d",
  "name": "GPGPU n-body 3D",
  "source": "ECE338",
  "source_ref": "programs/nbody-3d",
  "status": "runnable",
  "runnable": true,
  "lease": {
    "duration_seconds": 180,
    "idle_timeout_seconds": 45,
    "extension_seconds": 60,
    "extension_allowed_when_queue_empty": true
  }
}
```

A non-runnable project:

```json
{
  "id": "ece338-gpgpu-mandelbrot",
  "name": "GPGPU Mandelbrot",
  "source": "ECE338",
  "source_ref": "programs/mandelbrot",
  "status": "source-only",
  "runnable": false,
  "lease": null
}
```

The backend may internally map `project_id -> demo definition`, but that is not a public API concept.

---

## Final Public REST API

### `GET /api/health`

Process liveness only.

Must be fast and must not touch:

- Vivado;
- UART;
- thermal hardware;
- artifacts;
- heavy database state.

Response:

```json
{
  "status": "ok",
  "service": "fpga-demo-api",
  "version": "0.1.0"
}
```

---

### `GET /api/status`

Fast cached platform snapshot.

Used for:

- initial frontend render;
- reconnect recovery;
- manual debugging;
- monitoring.

Must not trigger slow hardware probes. Hardware state is refreshed by background monitor or session admission checks.

Response:

```json
{
  "api": {"status": "ok"},
  "board": {
    "available": true,
    "mode": "idle",
    "locked_by_session_id": null
  },
  "thermal": {
    "available": true,
    "temperature_c": 58.1,
    "max_temperature_c": 90.0,
    "checked_at": "2026-08-13T13:35:34Z",
    "stale": true,
    "reason": null
  },
  "sessions": {
    "active_session_id": null,
    "queued": 0
  }
}
```

Public `?refresh=true` is intentionally rejected. Public users must not be able to force Vivado/XADC probes.

---

### `GET /api/projects`

Single public project catalog.

This endpoint answers both:

- what real projects exist;
- which of them can currently be leased on the FPGA.

Rules:

- no fake placeholders;
- every project maps to reviewed source metadata;
- no local absolute paths in public output;
- no board access;
- no slow scanning on every request;
- runnable projects include lease policy.

Initial real ECE338 entries:

```text
ece338-gpgpu-nbody-3d    programs/nbody-3d    runnable
ece338-gpgpu-nbody-2d    programs/nbody       source-only
ece338-gpgpu-mandelbrot  programs/mandelbrot  source-only
ece338-gpgpu-differences programs/differences source-only
ece338-gpgpu-sobel       programs/sobel       source-only
ece338-gpgpu-simple      programs/simple      source-only
ece338-gpgpu-stacktest   programs/stacktest   source-only
```

---

### `POST /api/sessions`

Request time-limited FPGA access for a runnable project.

Request:

```json
{
  "project_id": "ece338-gpgpu-nbody-3d"
}
```

Functionality:

1. validate request shape strictly;
2. reject unknown fields;
3. verify project exists;
4. verify project is runnable;
5. enforce one active/queued session per requester;
6. enforce global single-board lease;
7. check thermal/board safety before granting access;
8. grant session immediately if board is idle and safe;
9. otherwise queue the session;
10. publish WebSocket session/queue/board events.

Active response:

```json
{
  "id": "sess_abc123",
  "project_id": "ece338-gpgpu-nbody-3d",
  "state": "active",
  "queue_position": null,
  "lease": {
    "starts_at": "...",
    "expires_at": "...",
    "remaining_seconds": 180,
    "duration_seconds": 180
  },
  "access": {
    "url": "/api/sessions/sess_abc123/demo/",
    "token_required": true
  }
}
```

Queued response:

```json
{
  "id": "sess_def456",
  "project_id": "ece338-gpgpu-nbody-3d",
  "state": "queued",
  "queue_position": 1,
  "lease": null,
  "access": null
}
```

Must not allow users to choose:

- UART port;
- Vivado/xsdb path;
- bitstream path;
- filesystem paths;
- shell commands;
- arbitrary programs.

---

### `GET /api/sessions`

List recent/active/queued sessions.

Used for frontend queue state and reconnect recovery.

Query params:

```text
state=queued|active|released|expired|cancelled|failed
limit=20
```

Returns summaries, not artifact contents.

Retention decision:

```text
active/queued sessions: kept until they finish
released/expired/cancelled/failed sessions: kept for 24 hours
finished-session cap: keep newest 200 even if retention window is larger
artifact folders for purged sessions: deleted with DB rows
```

This endpoint is for recent operational state, not analytics. Long-term usage analytics should be a separate aggregated metrics table later, not an ever-growing session list.

---

### `GET /api/sessions/{session_id}`

Fetch one session snapshot.

Used for:

- page reconnect;
- queue position checks;
- result/debug view.

Must not probe hardware or return local paths.

---

### `DELETE /api/sessions/{session_id}`

Release or cancel a session.

Behavior:

- queued session -> cancelled;
- active session -> released;
- next waiting session is promoted if board is safe;
- session/queue/board WebSocket events are emitted.

This is required so users can release the board before lease expiry.

---

### `POST /api/sessions/{session_id}/extend`

Request a bounded lease extension.

Policy:

- only active sessions can extend;
- extension is denied if another session is queued;
- total session duration is capped;
- future implementation should verify ownership before extending.

---

### `GET /api/sessions/{session_id}/artifacts/{artifact_name}`

Fetch a manifest-scoped artifact.

Examples:

```text
session.log
programming.log
summary.json
```

Rules:

- artifact must exist in the session artifact manifest;
- no arbitrary file reads;
- no `../` traversal;
- no absolute paths;
- explicit content type.

---

## Public WebSocket API

### Endpoint

```text
WS /api/ws
```

Public URL:

```text
wss://fpga.njason.dev/api/ws
```

### Role

The WebSocket is for live platform state:

- board/thermal updates;
- queue changes;
- session lifecycle updates;
- setup/programming logs;
- safety lockout events;
- heartbeat.

It does not:

- submit sessions initially;
- download artifacts;
- implement GPGPU visualization/control;
- run arbitrary board commands.

### Client messages

```json
{"type":"subscribe","channels":["board","queue","sessions"]}
{"type":"subscribe_session","session_id":"sess_abc123","logs":true,"after_sequence":0}
{"type":"unsubscribe_session","session_id":"sess_abc123"}
{"type":"ping","nonce":"abc"}
```

### Server events

```text
hello
subscribed
board.status
queue.snapshot
queue.changed
session.created
session.updated
session.snapshot
session.granted/session.ready later
session.log
session.finished
artifact.created
safety.lockout later
pong
error
```

Logs are live over WebSocket. Durable logs are artifacts.

---

## Two Users Competing for FPGA Access

There is exactly one active board lease.

If two users request the same runnable project:

```text
User A -> POST /api/sessions {project_id:e...nbody-3d}
User B -> POST /api/sessions {project_id:e...nbody-3d}
```

Then:

```text
User A -> active session if board is idle
User B -> queued session, queue_position=1
```

The backend must enforce this transactionally and with an in-process board/session lock.

### Lease policy

Initial recommendation:

```text
default lease: 180 seconds
idle timeout: 45 seconds
expiry warning: 30 seconds before end
extension: 60 seconds only if nobody is waiting
max total session: 300 seconds
```

### Fairness policy

- FIFO queue;
- one queued/active session per requester/IP;
- no indefinite extension if someone is waiting;
- active user may release early;
- queued sessions wait until board is safe and free.

### Safety policy

Queued sessions are not granted if:

- FPGA is too hot;
- thermal state is unavailable;
- board is in lockout;
- previous cleanup failed;
- hardware manager is unhealthy.

---

## Existing GPGPU App Integration

The existing GPGPU web app should be integrated as a session-owned project surface:

```text
/api/sessions/{session_id}/demo/
```

The platform controls:

- who has access;
- lease time;
- queue;
- board safety;
- setup/cleanup.

The GPGPU app controls its own visualization/UI. The platform WebSocket does not implement GPGPU frames or camera/demo controls.

---

## Endpoints Explicitly Not Public

```text
GET  /api/demos
POST /api/jobs
GET  /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/logs
POST /api/worker/run-next
GET  /api/status?refresh=true
GET  /api/thermal
GET  /api/queue
```

Internal demo definitions and internal action/job records may exist in code/database, but they are not public API resources.

---

## Final Minimal Public API

REST:

```text
GET    /api/health
GET    /api/status
GET    /api/projects
POST   /api/sessions
GET    /api/sessions
GET    /api/sessions/{session_id}
DELETE /api/sessions/{session_id}
POST   /api/sessions/{session_id}/extend
GET    /api/sessions/{session_id}/artifacts/{artifact_name}
GET/*  /api/sessions/{session_id}/demo/
```

WebSocket:

```text
WS /api/ws
```

Summary:

```text
Projects = what users select
Runnable project = project with lease capability
Sessions = public time-limited access to the board
Internal demos/actions/jobs = implementation details
REST = snapshots, session lifecycle, artifact downloads
WebSocket = live queue/session/board/log events
Existing GPGPU app = integrated as the session UI, not rewritten
```
