from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fpga_agent.fpga import FaultType, FPGAFault, FPGAState, FPGATelemetry, JTAGTargetContext
from web_api.api import create_api
from web_api.board import BoardManager
from web_api.config import SessionConfig, WebApiConfig
from web_api.demo_loader import DemoDefinition
from web_api.sessions import SessionManager

PORTFOLIO = "https://njason.dev"


def make_state(**updates) -> FPGAState:
    state = FPGAState(
        target_ctx=JTAGTargetContext(cable_serial="CABLE-SECRET", fpga_ctx="jtag-ctx-7", fpga_name="xc7z020"),
        telemetry=FPGATelemetry(temperature_c=45.56),
    )
    return state.model_copy(update=updates)


def make_board(config: WebApiConfig | None = None) -> BoardManager:
    config = config or WebApiConfig(board_label="Smart Zynq SL", public_cors_origins=(PORTFOLIO,))
    demos = {
        "gpgpu-nbody": DemoDefinition(id="gpgpu-nbody", name="GPGPU n-body simulator", root=Path(".")),
        "dvd-logo-video": DemoDefinition(id="dvd-logo-video", name="DVD Logo HDMI", root=Path(".")),
    }
    board = BoardManager(agent=None, config=config, demos=demos, sessions=SessionManager(SessionConfig()))
    board.device_id = "210299730789"
    board.fpga_state = make_state()
    board._agent_connected = True
    return board


def test_snapshot_is_public_safe():
    snapshot = make_board().public_snapshot()

    assert snapshot == {
        "online": True,
        "name": "Smart Zynq SL",
        "fpga": "xc7z020",
        "status": "idle",
        "mode": "demo",
        "temperature_c": 45.6,
        "healthy": True,
        "faults": [],
        "active_demo": None,
        "queue_length": 0,
        "demos": [
            {"id": "gpgpu-nbody", "name": "GPGPU n-body simulator"},
            {"id": "dvd-logo-video", "name": "DVD Logo HDMI"},
        ],
        "updated_at": snapshot["updated_at"],
    }
    text = json.dumps(snapshot)
    for secret in ("210299730789", "CABLE-SECRET", "jtag-ctx-7"):
        assert secret not in text


def test_snapshot_reports_faults_by_type_only():
    board = make_board()
    board.fpga_state = make_state(faults=[
        FPGAFault(type=FaultType.OVER_TEMPERATURE, bitstream_id="secret.bit"),
    ])

    snapshot = board.public_snapshot()

    assert snapshot["healthy"] is False
    assert snapshot["faults"] == ["over_temperature"]
    assert "secret.bit" not in json.dumps(snapshot)


def test_snapshot_offline_when_agent_disconnected():
    board = make_board()
    board._agent_connected = False

    snapshot = board.public_snapshot()

    assert snapshot["online"] is False
    assert snapshot["status"] == "offline"
    assert snapshot["temperature_c"] is None


def test_snapshot_shows_active_demo_and_queue():
    async def scenario():
        board = make_board()
        await board.sessions.create("user-a", "gpgpu-nbody")
        await board.sessions.begin_next()
        await board.sessions.create("user-b", "dvd-logo-video")
        return board.public_snapshot()

    snapshot = asyncio.run(scenario())

    assert snapshot["active_demo"] == "gpgpu-nbody"
    assert snapshot["queue_length"] == 1
    assert "user-a" not in json.dumps(snapshot)


def test_subscription_gets_initial_and_changed_snapshots_only():
    async def scenario():
        board = make_board()
        queue = board.open_public_subscription()
        first = queue.get_nowait()

        await board._broadcast({"type": "noop"})
        unchanged = queue.get_nowait()

        await board._broadcast({"type": "noop"})
        assert queue.empty()

        board.fpga_state = make_state(telemetry=FPGATelemetry(temperature_c=51.0))
        await board._broadcast({"type": "board.updated"})
        changed = queue.get_nowait()

        board.close_public_subscription(queue)
        return first, unchanged, changed, board

    first, unchanged, changed, board = asyncio.run(scenario())

    assert first["temperature_c"] == 45.6
    assert unchanged == first
    assert changed["temperature_c"] == 51.0
    assert not board._public_subscribers


def make_client(board: BoardManager) -> TestClient:
    app = FastAPI()
    app.include_router(create_api(board, httpx.AsyncClient(), config=board.config))
    return TestClient(app)


def test_public_board_endpoint_allows_configured_origin():
    client = make_client(make_board())

    response = client.get("/api/public/board", headers={"Origin": PORTFOLIO})

    assert response.status_code == 200
    assert response.json()["name"] == "Smart Zynq SL"
    assert response.headers["access-control-allow-origin"] == PORTFOLIO
    assert response.headers["cache-control"] == "public, max-age=10"


def test_public_board_endpoint_rejects_other_origins():
    client = make_client(make_board())

    response = client.get("/api/public/board", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_public_stream_sends_snapshot_then_keepalive():
    config = WebApiConfig(public_cors_origins=(PORTFOLIO,), public_keepalive_seconds=0.01)
    board = make_board(config)
    endpoint = next(
        route.endpoint for route in create_api(board, httpx.AsyncClient(), config=config).routes
        if getattr(route, "path", "") == "/api/public/board/stream"
    )

    class ConnectedRequest:
        headers = {"origin": PORTFOLIO}

        async def is_disconnected(self):
            return False

    async def scenario():
        response = await endpoint(ConnectedRequest())
        body = response.body_iterator
        chunks = [await anext(body) for _ in range(3)]
        await body.aclose()
        return response, chunks

    response, chunks = asyncio.run(scenario())

    assert response.media_type == "text/event-stream"
    assert response.headers["access-control-allow-origin"] == PORTFOLIO
    assert response.headers["x-accel-buffering"] == "no"
    assert chunks[0] == "retry: 5000\n\n"
    assert chunks[1].startswith("event: board\ndata: ")
    assert json.loads(chunks[1].split("data: ", 1)[1])["fpga"] == "xc7z020"
    assert chunks[2] == ": keepalive\n\n"
    assert not board._public_subscribers


STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "web_api" / "static"


@pytest.mark.skipif(not STATIC_DIR.is_dir(), reason="frontend not built (web_api.main mounts src/web_api/static)")
def test_public_endpoints_do_not_set_visitor_cookie():
    from web_api import main

    client = TestClient(main.app)

    public = client.get("/api/public/board")
    private = client.get("/api/status")

    assert "set-cookie" not in public.headers
    assert main.config.user_cookie in private.headers.get("set-cookie", "")
