from contextlib import asynccontextmanager
import logging
import os

from rich.logging import RichHandler
import uvicorn
from fastapi import FastAPI

from .fpga import FPGAMode
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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float") from exc

agent = Agent(
    AgentConfig(
        discovery_interval_seconds=_env_float("FPGA_DISCOVERY_INTERVAL_SECONDS", 10.0),
        telemetry_interval_seconds=_env_float("FPGA_TELEMETRY_INTERVAL_SECONDS", 2.0),
        discovery_timeout_seconds=_env_float("FPGA_DISCOVERY_TIMEOUT_SECONDS", 5.0),
        telemetry_timeout_seconds=_env_float("FPGA_TELEMETRY_TIMEOUT_SECONDS", 5.0),
        over_temperature_c=_env_float("FPGA_OVER_TEMPERATURE_C", 75.0),
        over_temperature_recovery_c=_env_float("FPGA_OVER_TEMPERATURE_RECOVERY_C", 60.0),
        mode=FPGAMode[os.getenv("FPGA_AGENT_MODE", "DEMO").upper()],
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
    socket_path = os.environ.get("FPGA_AGENT_SOCKET", "/tmp/fpga-agent.sock")

    uvicorn.run(
        app,
        uds=socket_path,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()