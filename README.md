# Live FPGA Lab

Live FPGA Lab is a small web platform for serving approved FPGA demos from a homelab bench. It combines an ECE-style hardware demo flow — programming a real board, running one demo at a time, and handling faults — with a browser UI that manages users, queueing, session handoff, and demo embedding.

The current app is built around one physical FPGA board and one active user session at a time.

## What is in this repository?

```text
.
├── demos/
│   └── gpgpu-nbody/           # Example Zynq PS/PL GPGPU n-body demo
├── src/
│   ├── fpga_agent/            # Local hardware agent; talks to the FPGA board
│   ├── web_api/               # FastAPI web app, queue/session manager, WS API
│   └── frontend/              # Vite + React SPA source
├── tests/                     # Pytest tests for backend/session behavior
├── docker/                    # Dockerfiles for web-api and fpga-agent images
├── docker-compose.yml         # Two-container deployment for x86 hardware hosts
├── .env.example               # Compose deployment settings template
├── pyproject.toml             # Python package, dependencies, CLI entry points
└── uv.lock                    # Locked Python dependency graph
```

Important generated/runtime paths:

```text
src/web_api/static/            # Built frontend output served by FastAPI
src/frontend/node_modules/     # Local npm dependencies, ignored by git
```

## Architecture

```text
Browser
  │
  │  /                         React dashboard, built into src/web_api/static/
  │  /api/ws                   WebSocket state + commands
  │  /api/sessions/.../demo    proxy to active demo backend
  ▼
web_api FastAPI app
  │
  │  anonymous cookie identifies each visitor
  │  SessionManager controls queue, active session, expiry, recent sessions
  │  BoardManager owns the board lifecycle and broadcasts state updates
  ▼
fpga_agent RPC app over Unix socket
  │
  │  /devices
  │  /devices/{id}
  │  /devices/{id}/events
  │  /devices/{id}/pl/program
  │  /devices/{id}/ps/program
  │  /devices/{id}/reset
  ▼
FPGA board + Xilinx tooling
```

### Main pieces

- `src/fpga_agent/`
  - Runs beside the hardware.
  - Exposes a FastAPI RPC server on a Unix socket, `/tmp/fpga-agent.sock` by default.
  - In Docker, set `FPGA_AGENT_SOCKET=/run/fpga-agent/fpga-agent.sock` so the socket can be shared with `web-api` through a named volume.
  - Discovers FPGA devices, tracks board state, streams board updates, programs PL/PS, resets the board, and latches faults.

- `src/web_api/`
  - Runs the user-facing FastAPI app on port `9121` by default.
  - Connects to the FPGA agent via the Unix socket.
  - Serves `/`, `/static/*`, `/api/status`, `/api/ws`, demo proxy routes, and artifact routes.
  - Manages anonymous users with the `fpga_user` cookie.

- `src/web_api/sessions.py`
  - In-memory queue/session state.
  - Session statuses: `queued`, `starting`, `active`, `ending`, `ended`.
  - End reasons: `user_ended`, `cancelled`, `expired`, `fpga_fault`, `board_offline`, `programming_failed`.
  - Only one active/starting session can own the board.

- `src/frontend/`
  - Vite + React dashboard source.
  - Built assets are emitted into `src/web_api/static/` using `base: '/static/'`.
  - `emptyOutDir: false` keeps `debug.html` from being deleted during frontend builds.

- `demos/`
  - Demo folders are loaded from `WEB_API_DEMO_DIR`, defaulting to `demos`.
  - Each immediate subfolder can define a `demo_definition.py` with `DEMO_DEFINITION` or `DEMO`.

## Requirements

- Python `>=3.11`
- [`uv`](https://docs.astral.sh/uv/) for Python dependency management
- Node.js + npm for the React frontend
- Xilinx/Vivado/Vitis tooling available on the machine that runs `fpga-agent`
- A reachable FPGA board/device for the current hardware-backed flow

The web API currently expects the FPGA agent to find at least one device at startup. If the agent reports no devices, the web API startup fails instead of running in mock mode.

## First-time setup

From the repository root:

```bash
uv sync --extra dev
npm install --prefix src/frontend
```

Build the frontend into the FastAPI static directory:

```bash
npm run build --prefix src/frontend
```

This creates/updates:

```text
src/web_api/static/index.html
src/web_api/static/assets/*
src/web_api/static/favicon.svg
```

## Running the platform

Use two terminals: one for the hardware agent and one for the web API.

### Terminal 1: FPGA agent

```bash
uv run fpga-agent
```

The agent listens on:

```text
/tmp/fpga-agent.sock
```

It is responsible for board discovery, board telemetry, programming, reset, and faults.

### Terminal 2: web API + frontend

```bash
uv run web-api
```

Default web URL:

```text
http://localhost:9121/
```

Useful routes:

```text
/              main React dashboard
/api/status    quick API/board availability check
/api/ws        WebSocket endpoint used by the frontend
```

## Configuration

The web API reads configuration from environment variables in `src/web_api/config.py`.

| Variable | Default | Purpose |
|---|---:|---|
| `WEB_API_HOST` | `0.0.0.0` | Bind host for the web API |
| `WEB_API_PORT` | `9121` | Bind port for the web API |
| `WEB_API_AGENT_SOCKET` | `/tmp/fpga-agent.sock` | Unix socket used to reach `fpga-agent` |
| `WEB_API_DEMO_DIR` | `demos` | Directory scanned for demo definitions |
| `WEB_API_USER_COOKIE` | `fpga_user` | Cookie name for anonymous user identity |
| `WEB_API_COOKIE_MAX_AGE_SECONDS` | `43200` | Anonymous user cookie lifetime |
| `WEB_API_COOKIE_SECURE` | `false` | Whether browser cookie is marked secure |
| `WEB_API_COOKIE_SAMESITE` | `lax` | Cookie SameSite policy |
| `WEB_API_WS_PROTOCOL` | `fpga-demo.v1` | WebSocket subprotocol |
| `WEB_API_SESSION_CONTENDED_SECONDS` | `300` | Active-session time window once someone is waiting |
| `WEB_API_SESSION_HANDOFF_SECONDS` | `60` | Handoff/reset window between sessions |

Example:

```bash
WEB_API_PORT=9121 \
WEB_API_SESSION_CONTENDED_SECONDS=300 \
WEB_API_SESSION_HANDOFF_SECONDS=60 \
uv run web-api
```

## How sessions and queueing work

1. A visitor opens `/`.
2. The web API assigns an anonymous `fpga_user` cookie if one does not exist.
3. The frontend opens `/api/ws` using subprotocol `fpga-demo.v1`.
4. The WebSocket sends an initial state packet containing:
   - board state
   - available demos
   - this user’s queue state
   - this user’s live session, if any
   - recent sessions
5. When the user starts a demo, the frontend sends a `session.create` command.
6. `SessionManager` creates a queued session.
7. If the board is idle, `BoardManager` moves the first queued session to `starting` and programs the board.
8. If programming succeeds, the session becomes `active`.
9. If another user is waiting, the active session receives an expiry time based on `WEB_API_SESSION_CONTENDED_SECONDS`.
10. If the active user ends the session, the session expires, programming fails, or the board faults/offlines, the session ends with a reason.
11. Queue and recent-session updates are broadcast to connected browsers.

The frontend uses the queue state to show:

- the user’s queue position
- ETA based on the active session expiry plus earlier queued users
- fault-aware ETA display when the board reports a fault/offline state
- recent sessions that reached the board/programming path

## WebSocket messages

The browser receives events such as:

```text
state.initial
board.updated
queue.updated
session.updated
recent_sessions.updated
command.result
ui.message
```

The browser sends commands such as:

```json
{ "type": "session.create", "request_id": "...", "demo_id": "gpgpu-nbody" }
{ "type": "session.end", "request_id": "...", "session_id": "..." }
```

## Adding a demo

Create a new immediate subdirectory under `demos/`:

```text
demos/my-demo/
└── demo_definition.py
```

Minimum definition:

```python
DEMO_DEFINITION = {
    "id": "my-demo",
    "name": "My FPGA demo",
    "description": "Short user-facing description.",
    "bitstream": "bitstream/my_design.bit",
    "ps7_init_tcl": "boot/ps7_init.tcl",
    "elf": "boot/app.elf",
}
```

Path fields are resolved relative to the demo folder unless they are absolute paths.

The loader also accepts `DEMO` for older demo definitions, but new demos should use `DEMO_DEFINITION`.

## Current bundled demo

`demos/gpgpu-nbody/` contains the current GPGPU n-body demo:

- PL bitstream: `bitstream/gpgpu_system_hello.bit`
- PS init script: `boot/ps7_init.tcl`
- PS application ELF: `boot/gpgpu_app.elf`
- interactive frontend/backend code under `demo/`
- runtime/program code under `programs/`

## Troubleshooting

### `/` returns missing file or stale UI

Rebuild the frontend:

```bash
npm run build --prefix src/frontend
```

### WebSocket shows disconnected/skeleton page

Check that the web API is still running and that the browser can reach:

```text
/api/ws
```

If you are testing disconnect behavior, temporarily stop `uv run web-api`; the frontend should switch to the skeleton page and reconnect when the server comes back.

### Web API fails on startup with no board

Start or fix the FPGA agent first:

```bash
uv run fpga-agent
```

Then confirm that it can discover at least one device. The current web API startup expects a real device from the agent.

### Queue ETA does not update

Check that the active session has an `active_expires_at` in `queue.updated` once it becomes active and somebody is waiting. A session still in `starting` has no expiry until programming succeeds.

### Faults block the ETA

If the board is `fault`, `offline`, or has a fault list, the frontend intentionally displays `Fault detected` in the ETA card instead of a countdown.

## Docker packaging and x86 deployment

The repository includes a two-container Docker deployment for an x86 machine that has the FPGA/JTAG/UART hardware and Xilinx tools installed.

```text
fpga-agent container
  ├─ runs XSDB/Vivado sessions
  ├─ accesses USB/JTAG adapters
  └─ publishes /run/fpga-agent/fpga-agent.sock through a named volume

web-api container
  ├─ serves the built React dashboard and FastAPI API on port 9121
  ├─ connects to fpga-agent through the shared Unix socket
  ├─ loads demos from /app/demos
  └─ launches the current gpgpu-nbody demo runtime when a session becomes active
```

### Files

```text
docker/fpga-agent.Dockerfile   hardware-agent image
docker/web-api.Dockerfile      web/API/frontend image
docker-compose.yml             full local deployment
.env.example                   deployment settings template
.dockerignore                  small build context and no secrets
```

The `web-api` Dockerfile builds the React frontend first, then copies the generated `src/web_api/static/` files into the runtime image.

### Prepare the deployment host

On the x86 host:

1. Install Docker Engine and Docker Compose.
2. Install/mount Xilinx/Vivado so this file exists inside the `fpga-agent` container at the same absolute path as the host:

   ```text
   /home/njason/Xilinx/2025.2/Vivado/settings64.sh
   ```

   The Compose file does this by mounting the host path from `HOST_XILINX_DIR` back to the same path read-only. Avoid remapping Xilinx to a different container path like `/opt/Xilinx`; generated `settings64.sh` files can source sibling files by absolute install path.
3. Plug in the FPGA JTAG/USB cable and the demo UART device.
4. Confirm the UART device path, usually:

   ```text
   /dev/ttyUSB0
   ```

### Configure Compose

Create a local `.env` from the template:

```bash
cp .env.example .env
```

Edit at least these values:

```env
HOST_XILINX_DIR=/home/njason/Xilinx
FPGA_AGENT_VIVADO_SETTINGS=/home/njason/Xilinx/2025.2/Vivado/settings64.sh
HOST_DEMO_UART=/dev/ttyUSB1
WEB_API_PUBLISHED_PORT=9121
```

If Vivado needs a license server or license file, set one of:

```env
XILINXD_LICENSE_FILE=
LM_LICENSE_FILE=
```

### Build and start

```bash
docker compose build
docker compose up -d
```

Check status and logs:

```bash
docker compose ps
docker compose logs -f fpga-agent
docker compose logs -f web-api
```

Verify the web API:

```bash
curl -i http://127.0.0.1:9121/api/status
curl -i http://127.0.0.1:9121/
```

### Updating a deployment

```bash
git pull
cp .env.example .env   # only for first install; do not overwrite a tuned .env
docker compose build
docker compose up -d
docker compose logs -f --tail=100
```

## Python package build

Build the Python package with:

```bash
uv build
```

The Python package includes `src/web_api` and `src/fpga_agent`. Build the frontend first if you want the latest React static assets included under `src/web_api/static/`.