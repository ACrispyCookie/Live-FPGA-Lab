from pathlib import Path
from time import perf_counter
from uuid import uuid4
import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .agent import Agent
from .fpga import FPGAState, FaultType
from fastapi.responses import StreamingResponse

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


class ReservedForProjectsRequest(BaseModel):
    reserved_for_projects: bool


def create_rpc_app(agent: Agent) -> FastAPI:
    app = FastAPI(title="FPGA Agent RPC", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def log_rpc_request(request: Request, call_next):
        request_id = uuid4().hex[:8]
        started = perf_counter()
        path = request.url.path
        logger.info("[bright_black]⇢ rpc[/] %s %s [dim]#%s[/]", request.method, path, request_id)
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (perf_counter() - started) * 1000
            logger.exception(
                "[bold red]✖ rpc[/] %s %s crashed in %.1fms [dim]#%s[/]",
                request.method,
                path,
                duration_ms,
                request_id,
            )
            raise

        duration_ms = (perf_counter() - started) * 1000
        status = response.status_code
        style = "green" if status < 400 else "yellow" if status < 500 else "red"
        symbol = "✓" if status < 400 else "◇" if status < 500 else "✖"
        logger.info(
            "[%s]%s rpc[/] %s %s → %s in %.1fms [dim]#%s[/]",
            style,
            symbol,
            request.method,
            path,
            status,
            duration_ms,
            request_id,
        )
        return response

    @app.get("/devices", response_model=list[str])
    async def list_devices():
        return [device.device_id for device in agent.list_devices()]

    @app.get("/devices/{device_id}", response_model=FPGAState)
    async def get_device(device_id: str):
        try:
            return agent.get_device(device_id)
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")

    @app.get("/devices/{device_id}/events")
    async def device_events(device_id: str):
        try:
            agent.get_device(device_id)
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")

        async def stream():
            async for state in agent.subscribe(device_id):
                yield f"data: {state.model_dump_json()}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/devices/{device_id}/pl/program", response_model=FPGAState)
    async def program_pl(device_id: str, request: ProgramPLRequest):
        try:
            return await agent.program_pl(device_id, Path(request.bitstream))
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/ps/program", response_model=FPGAState)
    async def program_ps(device_id: str, request: ProgramPSRequest):
        try:
            return await agent.program_ps(
                device_id,
                ps7_init_tcl=Path(request.ps7_init_tcl),
                elf=Path(request.elf),
                reset_processor=request.reset_processor,
                continue_after_download=request.continue_after_download,
            )
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/reset", response_model=FPGAState)
    async def reset_board(device_id: str):
        try:
            return await agent.reset_board(device_id)
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/faults/clear", response_model=FPGAState)
    async def clear_fault(device_id: str, request: ClearFaultRequest):
        try:
            return agent.clear_device_fault(device_id, request.fault_type)
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/devices/{device_id}/reserved-for-projects", response_model=FPGAState)
    async def set_reserved_for_projects(device_id: str, request: ReservedForProjectsRequest):
        try:
            return agent.set_reserved_for_projects(
                device_id,
                request.reserved_for_projects,
            )
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")

    return app
