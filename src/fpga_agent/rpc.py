from pathlib import Path
from time import perf_counter
from uuid import uuid4
import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .agent import Agent
from .fpga import FPGAState, FaultType

logger = logging.getLogger("rpc")


class ProgramPLRequest(BaseModel):
    bitstream: str


class ProgramPSRequest(BaseModel):
    ps7_init_tcl: str
    elf: str
    reset_processor: bool = True
    continue_after_download: bool = True


class ClearFaultRequest(BaseModel):
    fault_type: FaultType


def create_rpc_app(agent: Agent) -> FastAPI:
    app = FastAPI(title="FPGA Agent RPC", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def log_rpc_request(request: Request, call_next):
        request_id = uuid4().hex[:8]
        started = perf_counter()
        path = request.url.path
        logger.info("[bold cyan]⇢ rpc[/] %s %s [dim]#%s[/]", request.method, path, request_id)
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (perf_counter() - started) * 1000
            logger.exception("[bold red]✖ rpc[/] %s %s failed in %.1fms [dim]#%s[/]", request.method, path, duration_ms, request_id)
            raise
        duration_ms = (perf_counter() - started) * 1000
        style = "green" if response.status_code < 400 else "yellow" if response.status_code < 500 else "red"
        logger.info(
            "[bold %s]⇠ rpc[/] %s %s → %s in %.1fms [dim]#%s[/]",
            style,
            request.method,
            path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    @app.get("/devices", response_model=list[str])
    async def list_devices():
        devices = agent.list_devices()
        logger.info("[cyan]◆ devices[/] listed count=%d", len(devices))
        return [device.device_id for device in devices]

    @app.get("/devices/{device_id}", response_model=FPGAState)
    async def get_device(device_id: str):
        try:
            device = agent.get_device(device_id)
            logger.info("[cyan]◆ device[/] %s status=%s faults=%d", device_id, device.status, len(device.faults))
            return device
        except KeyError:
            logger.warning("[yellow]◇ device[/] unknown device=%s", device_id)
            raise HTTPException(404, "Unknown FPGA device")

    @app.post("/devices/{device_id}/pl/program", response_model=FPGAState)
    async def program_pl(device_id: str, request: ProgramPLRequest):
        logger.info("[bold magenta]▶ program-pl[/] device=%s bitstream=%s", device_id, request.bitstream)
        try:
            device = await agent.program_pl(device_id, Path(request.bitstream))
            logger.info("[bold green]✓ program-pl[/] device=%s status=%s bitstream=%s", device_id, device.status, _short(device.bitstream_id))
            return device
        except KeyError:
            logger.warning("[yellow]◇ program-pl[/] unknown device=%s", device_id)
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            logger.error("[bold red]✖ program-pl[/] device=%s error=%s", device_id, exc)
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/ps/program", response_model=FPGAState)
    async def program_ps(device_id: str, request: ProgramPSRequest):
        logger.info(
            "[bold magenta]▶ program-ps[/] device=%s elf=%s reset=%s continue=%s",
            device_id,
            request.elf,
            request.reset_processor,
            request.continue_after_download,
        )
        try:
            device = await agent.program_ps(
                device_id,
                ps7_init_tcl=Path(request.ps7_init_tcl),
                elf=Path(request.elf),
                reset_processor=request.reset_processor,
                continue_after_download=request.continue_after_download,
            )
            logger.info("[bold green]✓ program-ps[/] device=%s status=%s", device_id, device.status)
            return device
        except KeyError:
            logger.warning("[yellow]◇ program-ps[/] unknown device=%s", device_id)
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            logger.error("[bold red]✖ program-ps[/] device=%s error=%s", device_id, exc)
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/reset", response_model=FPGAState)
    async def reset_board(device_id: str):
        logger.info("[bold magenta]▶ reset[/] device=%s", device_id)
        try:
            device = await agent.reset_board(device_id)
            logger.info("[bold green]✓ reset[/] device=%s status=%s faults=%d", device_id, device.status, len(device.faults))
            return device
        except KeyError:
            logger.warning("[yellow]◇ reset[/] unknown device=%s", device_id)
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            logger.error("[bold red]✖ reset[/] device=%s error=%s", device_id, exc)
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/faults/clear", response_model=FPGAState)
    async def clear_fault(device_id: str, request: ClearFaultRequest):
        logger.info("[bold magenta]▶ clear-fault[/] device=%s fault=%s", device_id, request.fault_type)
        try:
            device = agent.clear_device_fault(device_id, request.fault_type)
            logger.info("[bold green]✓ clear-fault[/] device=%s remaining=%d", device_id, len(device.faults))
            return device
        except KeyError:
            logger.warning("[yellow]◇ clear-fault[/] unknown device=%s", device_id)
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            logger.error("[bold red]✖ clear-fault[/] device=%s error=%s", device_id, exc)
            raise HTTPException(409, str(exc))

    return app


def _short(value: str | None) -> str:
    return value[:12] if value else "none"
