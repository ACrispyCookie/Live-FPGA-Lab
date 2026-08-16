from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

import secrets
import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from .board import BoardError, BoardManager
from .config import WebApiConfig

logger = logging.getLogger("api")

DEFAULT_CONFIG = WebApiConfig()
USER_COOKIE = DEFAULT_CONFIG.user_cookie
WS_PROTOCOL = DEFAULT_CONFIG.ws_protocol

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

def create_api(board: BoardManager, proxy_client: httpx.AsyncClient, *, config: WebApiConfig = DEFAULT_CONFIG) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/status")
    async def status():
        return {
            "status": "ok",
            "board": board.available,
        }

    @router.websocket("/ws")
    async def websocket(ws: WebSocket):
        user_id = ws.cookies.get(config.user_cookie)
        if not user_id:
            await ws.close(code=1008, reason="Missing anonymous user")
            return

        await ws.accept(subprotocol=config.ws_protocol if config.ws_protocol in ws.headers.get("sec-websocket-protocol", "") else None)

        outgoing: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)
        await outgoing.put({
            "type": "state.initial",
            **(await board.snapshot_for(user_id)),
        })

        async def sender():
            while True:
                await ws.send_json(await outgoing.get())

        async def forward_updates():
            async for event in board.subscribe(user_id):
                await outgoing.put(_json(event))

        sender_task = asyncio.create_task(sender())
        updates_task = asyncio.create_task(forward_updates())

        try:
            while True:
                message = await ws.receive_json()
                request_id = message.get("request_id")

                try:
                    match message.get("type"):
                        case "session.create":
                            session = await board.create_session(user_id, message["demo_id"])
                            await outgoing.put({
                                "type": "command.result",
                                "request_id": request_id,
                                "ok": True,
                                "session_id": session.id,
                            })

                        case "session.end":
                            await board.end_session(user_id, message["session_id"])
                            await outgoing.put({
                                "type": "command.result",
                                "request_id": request_id,
                                "ok": True,
                            })

                        case _:
                            await outgoing.put({
                                "type": "command.result",
                                "request_id": request_id,
                                "ok": False,
                                "error": {
                                    "code": "unknown_command",
                                    "message": "Unknown command.",
                                },
                            })

                except KeyError as exc:
                    await outgoing.put({
                        "type": "command.result",
                        "request_id": request_id,
                        "ok": False,
                        "error": {
                            "code": "invalid_command",
                            "message": f"Missing field: {exc.args[0]}",
                        },
                    })

                except BoardError as exc:
                    await outgoing.put({
                        "type": "command.result",
                        "request_id": request_id,
                        "ok": False,
                        "error": {
                            "code": exc.code,
                            "message": str(exc),
                        },
                    })

                except Exception:
                    logger.exception("WebSocket command failed")
                    await outgoing.put({
                        "type": "command.result",
                        "request_id": request_id,
                        "ok": False,
                        "error": {
                            "code": "internal_error",
                            "message": "Command failed.",
                        },
                    })

        except WebSocketDisconnect:
            pass
        finally:
            sender_task.cancel()
            updates_task.cancel()

            with suppress(asyncio.CancelledError):
                await sender_task

            with suppress(asyncio.CancelledError):
                await updates_task

    @router.api_route(
        "/sessions/{session_id}/demo",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    @router.api_route(
        "/sessions/{session_id}/demo/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def demo_proxy(request: Request, session_id: str, path: str = ""):
        user_id = _http_user(request)

        try:
            backend = board.demo_backend_for(user_id, session_id)
        except BoardError as exc:
            raise HTTPException(exc.status_code, str(exc))

        url = f"{backend.rstrip('/')}/{path}"
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS | {"host", "cookie"}
        }

        response = await proxy_client.request(
            request.method,
            url,
            params=request.query_params,
            headers=headers,
            content=await request.body(),
            follow_redirects=False,
        )

        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS | {"content-length"}
        }

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers,
        )

    @router.get("/sessions/{session_id}/artifacts/{name}")
    async def artifact(request: Request, session_id: str, name: str):
        user_id = _http_user(request)

        try:
            path = board.artifact_for(user_id, session_id, name)
        except BoardError as exc:
            raise HTTPException(exc.status_code, str(exc))

        path = Path(path)
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")

        return FileResponse(path)

    return router


def _http_user(request: Request) -> str:
    user_id = request.cookies.get(getattr(request.app.state, "config", DEFAULT_CONFIG).user_cookie)
    if not user_id:
        raise HTTPException(401, "Missing anonymous user")
    return user_id


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value