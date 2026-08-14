from __future__ import annotations

import os
import queue
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from fpga_demo_platform.demos import list_projects, project_to_dict
from fpga_demo_platform.sessions import SessionLimitExceeded, SessionManager, SessionStartFailed, session_to_dict
from fpga_demo_platform.thermal import HardwareUnavailable


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str


def create_app(*, session_manager: SessionManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session_manager.start_board_monitor(interval_seconds=_monitor_interval_seconds())
        try:
            yield
        finally:
            session_manager.stop_board_monitor()

    app = FastAPI(title="FPGA Demo Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )


    @app.get("/")
    def service_root() -> dict[str, str]:
        return {"service": "fpga-demo-api", "status": "ok"}

    @app.get("/health")
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "fpga-demo-api", "version": "0.1.0"}

    @app.get("/api/status")
    def api_status(request: Request) -> dict[str, Any]:
        if "refresh" in request.query_params:
            raise HTTPException(status_code=422, detail={"error": {"code": "unsupported_parameter", "message": "status refresh is not public; use cached status and WebSocket updates"}})
        return session_manager.status_snapshot()

    @app.get("/api/projects")
    def api_projects() -> list[dict[str, Any]]:
        return [project_to_dict(project) for project in list_projects()]

    @app.post("/api/sessions", status_code=status.HTTP_201_CREATED)
    def create_session(body: SessionRequest, request: Request) -> dict[str, Any]:
        try:
            session = session_manager.request_session(body.project_id, requester=_requester(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": "unknown_project", "message": str(exc)}}) from exc
        except HardwareUnavailable as exc:
            raise HTTPException(status_code=503, detail={"error": {"code": "hardware_unavailable", "message": str(exc), "thermal": exc.status.to_dict()}}) from exc
        except SessionLimitExceeded as exc:
            raise HTTPException(status_code=429, detail={"error": {"code": "session_limit", "message": str(exc)}}) from exc
        except SessionStartFailed as exc:
            try:
                failed = session_manager.get(exc.session_id)
                payload = session_to_dict(failed, artifacts=session_manager.artifacts_for_session(exc.session_id), include_owner_token=True)
                payload["startup_logs"] = session_manager.logs_for_session(exc.session_id)
            except Exception:
                payload = {"id": exc.session_id, "startup_logs": session_manager.logs_for_session(exc.session_id)}
            raise HTTPException(status_code=500, detail={"error": {"code": "session_start_failed", "message": str(exc)}, "session": payload}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": {"code": "invalid_session_request", "message": str(exc)}}) from exc
        payload = session_to_dict(session, artifacts=session_manager.artifacts_for_session(session.id), include_owner_token=True)
        payload["startup_logs"] = session_manager.logs_for_session(session.id)
        return payload

    @app.get("/api/sessions")
    def list_sessions(limit: int = 20, state: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        return [session_to_dict(session, artifacts=session_manager.artifacts_for_session(session.id)) for session in session_manager.list_recent(limit=limit, state=state)]

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            session = session_manager.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": "unknown_session", "message": str(exc)}}) from exc
        return session_to_dict(session, artifacts=session_manager.artifacts_for_session(session.id))

    @app.delete("/api/sessions/{session_id}")
    def release_session(session_id: str, request: Request) -> dict[str, Any]:
        try:
            session_manager.require_owner(session_id, _owner_token(request))
            session = session_manager.release(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": "unknown_session", "message": str(exc)}}) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"error": {"code": "not_session_owner", "message": str(exc)}}) from exc
        return session_to_dict(session, artifacts=session_manager.artifacts_for_session(session.id))

    @app.post("/api/sessions/{session_id}/extend")
    def extend_session(session_id: str, request: Request) -> dict[str, Any]:
        try:
            session_manager.require_owner(session_id, _owner_token(request))
            session = session_manager.extend(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": "unknown_session", "message": str(exc)}}) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"error": {"code": "not_session_owner", "message": str(exc)}}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": {"code": "extension_denied", "message": str(exc)}}) from exc
        return session_to_dict(session, artifacts=session_manager.artifacts_for_session(session.id))

    @app.api_route("/api/sessions/{session_id}/demo/", methods=["GET", "POST"])
    @app.api_route("/api/sessions/{session_id}/demo/{demo_path:path}", methods=["GET", "POST"])
    async def proxy_demo(session_id: str, request: Request, demo_path: str = ""):
        try:
            runtime = session_manager.runtime_for_session(session_id, _owner_token(request))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": "unknown_session", "message": str(exc)}}) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"error": {"code": "not_session_owner", "message": str(exc)}}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"error": {"code": "demo_not_active", "message": str(exc)}}) from exc
        body = await request.body() if request.method.upper() == "POST" else None
        response = _proxy_upstream(request, _demo_upstream_url(runtime, demo_path, request), body=body)
        if request.query_params.get("token"):
            response.set_cookie(_session_cookie_name(session_id), request.query_params["token"], httponly=True, samesite="lax", path=f"/api/sessions/{session_id}/demo")
        return response

    @app.get("/api/sessions/{session_id}/artifacts/{artifact_name}")
    def get_artifact(session_id: str, artifact_name: str) -> FileResponse:
        try:
            artifact = session_manager.get_artifact(session_id, artifact_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": {"code": "invalid_artifact_name", "message": str(exc)}}) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": {"code": "unknown_artifact", "message": str(exc)}}) from exc
        return FileResponse(artifact.path, media_type=artifact.content_type, filename=artifact.name)

    @app.websocket("/api/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        subscriber = session_manager.event_bus.subscribe()
        subscribed_channels: set[str] = set()
        subscribed_sessions: dict[str, bool] = {}
        await websocket.send_json({"type": "hello", "server_time": _now(), "capabilities": ["board", "queue", "sessions", "logs", "thermal"]})
        try:
            while True:
                try:
                    message = await _receive_or_event(websocket, subscriber)
                except WebSocketDisconnect:
                    return
                if message.get("source") == "event":
                    event = message["event"]
                    payload = {"type": event.type, "sequence": event.sequence, **event.payload}
                    if _should_send_event(event.type, payload, subscribed_channels, subscribed_sessions):
                        await websocket.send_json(payload)
                    continue
                data = message["data"]
                msg_type = data.get("type")
                if msg_type == "subscribe":
                    channels = {str(channel) for channel in data.get("channels", []) if channel in {"board", "queue", "sessions"}}
                    subscribed_channels.update(channels)
                    await websocket.send_json({"type": "subscribed", "channels": sorted(channels)})
                    if "queue" in channels:
                        await websocket.send_json({"type": "queue.snapshot", "queue": session_manager.queue_summary()})
                    if "board" in channels:
                        await websocket.send_json({"type": "board.status", **session_manager.board_status()})
                elif msg_type == "subscribe_session":
                    session_id = str(data.get("session_id", ""))
                    logs = bool(data.get("logs", False))
                    try:
                        session = session_manager.get(session_id)
                    except KeyError:
                        await websocket.send_json({"type": "error", "code": "unknown_session", "message": "Unknown session"})
                    else:
                        subscribed_sessions[session_id] = logs
                        await websocket.send_json({"type": "session.snapshot", "session": session_to_dict(session, artifacts=session_manager.artifacts_for_session(session.id))})
                elif msg_type == "unsubscribe_session":
                    subscribed_sessions.pop(str(data.get("session_id", "")), None)
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong", "nonce": data.get("nonce")})
                elif msg_type == "__tick":
                    session_manager.check_session_policy()
                    continue
                else:
                    await websocket.send_json({"type": "error", "code": "bad_message", "message": "Unknown message type"})
        finally:
            for session_id in list(subscribed_sessions):
                session_manager.cancel_if_queued(session_id)
            session_manager.event_bus.unsubscribe(subscriber)

    return app


async def _receive_or_event(websocket: WebSocket, subscriber: queue.Queue):
    import anyio

    try:
        event = subscriber.get_nowait()
        return {"source": "event", "event": event}
    except queue.Empty:
        pass

    with anyio.move_on_after(0.1) as scope:
        data = await websocket.receive_json()
        return {"source": "client", "data": data}
    if scope.cancel_called:
        try:
            event = subscriber.get_nowait()
            return {"source": "event", "event": event}
        except queue.Empty:
            return {"source": "client", "data": {"type": "__tick"}}
    return {"source": "client", "data": {"type": "__tick"}}


def _should_send_event(event_type: str, payload: dict[str, Any], channels: set[str], sessions: dict[str, bool]) -> bool:
    if event_type == "board.status":
        return "board" in channels
    if event_type == "queue.changed":
        return "queue" in channels
    if event_type.startswith("safety."):
        session_id = payload.get("session_id") or (payload.get("session") or {}).get("id")
        return "board" in channels or session_id in sessions
    if event_type.startswith("session.") or event_type == "artifact.created":
        session = payload.get("session") or {}
        session_id = payload.get("session_id") or session.get("id")
        if session_id in sessions:
            return event_type != "session.log" or sessions[session_id]
        return "sessions" in channels and event_type != "session.log"
    return False


def _cors_origins() -> list[str]:
    configured = os.environ.get("FPGA_DEMO_CORS_ORIGINS", "*")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or ["*"]


def _monitor_interval_seconds() -> float:
    return max(1.0, float(os.environ.get("FPGA_DEMO_BOARD_MONITOR_SECONDS", "15")))


def _requester(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _owner_token(request: Request) -> str | None:
    session_id = request.path_params.get("session_id")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    header = request.headers.get("x-session-token")
    if header:
        return header.strip()
    query = request.query_params.get("token")
    if query:
        return query.strip()
    if isinstance(session_id, str):
        cookie = request.cookies.get(_session_cookie_name(session_id))
        if cookie:
            return cookie.strip()
    return None


def _session_cookie_name(session_id: str) -> str:
    return f"fpga_session_{session_id}"


def _demo_upstream_url(runtime: dict[str, Any], demo_path: str, request: Request) -> str:
    path = "/" + demo_path.lstrip("/")
    query_items = [(key, value) for key, value in request.query_params.multi_items() if key != "token"]
    query = urllib.parse.urlencode(query_items)
    return f"http://127.0.0.1:{int(runtime['port'])}{path}" + (f"?{query}" if query else "")


def _proxy_upstream(request: Request, url: str, *, body: bytes | None = None):
    headers = {"content-type": request.headers.get("content-type", "application/octet-stream")}
    upstream_request = urllib.request.Request(url, data=body, headers=headers, method=request.method.upper())
    try:
        upstream = urllib.request.urlopen(upstream_request, timeout=None if url.endswith("/events") else 15)
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status_code=exc.code, media_type=exc.headers.get("content-type"))
    content_type = upstream.headers.get("content-type", "application/octet-stream")
    if "text/event-stream" in content_type:
        return StreamingResponse(upstream, media_type=content_type)
    return Response(upstream.read(), status_code=upstream.status, media_type=content_type)


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def app_from_paths(db_path: str | Path, artifacts_dir: str | Path) -> FastAPI:
    manager = SessionManager(db_path, artifacts_dir)
    return create_app(session_manager=manager)
