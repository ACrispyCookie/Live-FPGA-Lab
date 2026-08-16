from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from fpga_agent.fpga import FPGAState

class AgentClient:
    def __init__(self, socket: str | Path):
        self.socket = str(socket)
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=self.socket),
            base_url="http://fpga-agent",
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def list_devices(self) -> list[str]:
        response = await self._client.get("/devices")
        response.raise_for_status()
        return response.json()

    async def get_device(self, device_id: str) -> FPGAState:
        response = await self._client.get(f"/devices/{device_id}")
        response.raise_for_status()
        return FPGAState.model_validate(response.json())

    async def program_pl(self, device_id: str, bitstream: str | Path) -> FPGAState:
        response = await self._client.post(
            f"/devices/{device_id}/pl/program",
            json={"bitstream": str(bitstream)},
        )
        response.raise_for_status()
        return FPGAState.model_validate(response.json())

    async def program_ps(
        self,
        device_id: str,
        *,
        ps7_init_tcl: str | Path,
        elf: str | Path,
        reset_processor: bool = True,
        continue_after_download: bool = True,
    ) -> FPGAState:
        response = await self._client.post(
            f"/devices/{device_id}/ps/program",
            json={
                "ps7_init_tcl": str(ps7_init_tcl),
                "elf": str(elf),
                "reset_processor": reset_processor,
                "continue_after_download": continue_after_download,
            },
        )
        response.raise_for_status()
        return FPGAState.model_validate(response.json())

    async def reset(self, device_id: str) -> FPGAState:
        response = await self._client.post(f"/devices/{device_id}/reset")
        response.raise_for_status()
        return FPGAState.model_validate(response.json())

    async def subscribe(self, device_id: str) -> AsyncIterator[FPGAState]:
        async with self._client.stream("GET", f"/devices/{device_id}/events") as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                yield FPGAState.model_validate(json.loads(line[6:]))