from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from rich.logging import RichHandler
import uvicorn

from .agent_client import AgentClient
from .api import create_api
from .board import BoardManager
from .config import WebApiConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=True)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

config = WebApiConfig.from_env()
agent = AgentClient(config.agent_socket)
proxy_client = httpx.AsyncClient()
board = BoardManager(agent, config=config)


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
app.state.config = config


@app.middleware("http")
async def anonymous_user(request: Request, call_next):
    user_id = request.cookies.get(config.user_cookie)
    created = user_id is None

    if created:
        user_id = secrets.token_urlsafe(32)

    request.state.user_id = user_id
    response = await call_next(request)

    if created:
        response.set_cookie(
            config.user_cookie,
            user_id,
            httponly=True,
            samesite=config.cookie_samesite,
            secure=config.cookie_secure,
            max_age=config.cookie_max_age_seconds,
        )

    return response


app.include_router(create_api(board, proxy_client, config=config))


def main() -> None:
    uvicorn.run(
        "web_api.main:app",
        host=config.host,
        port=config.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
