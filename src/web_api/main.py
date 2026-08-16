from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request

from .agent_client import AgentClient
from .api import USER_COOKIE, create_api
from .board import BoardManager

AGENT_SOCKET = Path("/tmp/fpga-agent.sock")

agent = AgentClient(AGENT_SOCKET)
proxy_client = httpx.AsyncClient()
board = BoardManager(agent)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await board.start()
    try:
        yield
    finally:
        await board.stop()
        await agent.close()
        await proxy_client.aclose()

app = FastAPI(
    title="FPGA Demo API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

@app.middleware("http")
async def anonymous_user(request: Request, call_next):
    user_id = request.cookies.get(USER_COOKIE)
    created = user_id is None

    if created:
        user_id = secrets.token_urlsafe(32)

    request.state.user_id = user_id
    response = await call_next(request)

    if created:
        response.set_cookie(
            USER_COOKIE,
            user_id,
            httponly=True,
            samesite="lax",
            secure=False,  # True behind HTTPS
            max_age=60 * 60 * 12,
        )

    return response

app.include_router(create_api(board, proxy_client))

def main() -> None:
    uvicorn.run(
        "web_api.main:app",
        host="0.0.0.0",
        port=8000,
        access_log=False,
    )

if __name__ == "__main__":
    main()