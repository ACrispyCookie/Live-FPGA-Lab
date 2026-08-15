from contextlib import asynccontextmanager
import logging

from rich.logging import RichHandler
import uvicorn
from fastapi import FastAPI

from .agent import Agent, AgentConfig
from .rpc import create_rpc_app

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=True)],
)

# Silence Uvicorn completely.
logging.getLogger("uvicorn").disabled = True
logging.getLogger("uvicorn.error").disabled = True
logging.getLogger("uvicorn.access").disabled = True


agent = Agent(
    AgentConfig(
        discovery_interval_seconds=10.0,
        telemetry_interval_seconds=1.0,
        over_temperature_c=40.0,
        over_temperature_recovery_c=30.0,
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent.start()
    try:
        yield
    finally:
        await agent.stop()


def main() -> None:
    app = create_rpc_app(agent)
    app.router.lifespan_context = lifespan

    uvicorn.run(
        app,
        uds="/tmp/fpga-agent.sock",
        access_log=False,
        log_config=None,
    )