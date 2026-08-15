from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import Agent
from .fpga import FPGAState, FaultType


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

    @app.get("/devices", response_model=list[FPGAState])
    async def list_devices():
        return agent.list_devices()

    @app.get("/devices/{device_id}", response_model=FPGAState)
    async def get_device(device_id: str):
        try:
            return agent.get_device(device_id)
        except KeyError:
            raise HTTPException(404, "Unknown FPGA device")

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

    return app