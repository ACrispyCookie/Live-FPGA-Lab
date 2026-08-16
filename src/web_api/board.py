from __future__ import annotations

import logging
import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Any

from fpga_agent.fpga import FPGAState

from .agent_client import AgentClient

logger = logging.getLogger("board")

class BoardError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class BoardManager:
    def __init__(self, agent: AgentClient):
        self.agent = agent
        self.primary_board: FPGAState | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._subscriber_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        logger.info("starting board manager")
        self._stopping.clear()
        await self._discover_primary_board()
        if self.primary_board is None:
            logger.info("no FPGA devices discovered by agent")
            return
        self._subscriber_task = asyncio.create_task(self._subscribe_primary_board())

    async def stop(self) -> None:
        logger.info("stopping board manager")
        self._stopping.set()
        if self._subscriber_task is not None:
            self._subscriber_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._subscriber_task
            self._subscriber_task = None

    async def subscribe(self, user_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue)
        logger.info(f"websocket subscribed user={user_id} subscribers={len(self._subscribers)}")
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
            logger.info(f"websocket unsubscribed user={user_id} subscribers={len(self._subscribers)}")

    def snapshot_for(self, user_id: str) -> dict[str, Any]:
        return {
            "board": self._board_payload(),
            "queue": {"items": []},
            "session": None,
            "demos": [],
        }

    async def create_session(self, user_id: str, demo_id: str):
        raise BoardError("not_implemented", "Session creation is not implemented yet.", status_code=501)

    async def end_session(self, user_id: str, session_id: str) -> None:
        raise BoardError("not_implemented", "Session ending is not implemented yet.", status_code=501)

    def demo_backend_for(self, user_id: str, session_id: str) -> str:
        raise BoardError("not_implemented", "Demo proxy is not implemented yet.", status_code=501)

    def artifact_for(self, user_id: str, session_id: str, name: str) -> Path:
        raise BoardError("not_implemented", "Artifact serving is not implemented yet.", status_code=501)

    async def _discover_primary_board(self) -> None:
        devices = await self.agent.list_devices()
        if not devices:
            async with self._lock:
                self.primary_board = None
            await self._publish_board_updated()
            return

        device_id = devices[0]
        board = await self.agent.get_device(device_id)
        async with self._lock:
            self.primary_board = board
        logger.info(f"selected primary board device={board.device_id} status={board.status} faults={len(board.faults)}")
        await self._publish_board_updated()

    async def _subscribe_primary_board(self) -> None:
        while not self._stopping.is_set():
            board = self.primary_board
            if board is None:
                return
            device_id = board.device_id
            try:
                async for update in self.agent.subscribe(device_id):
                    await self._apply_agent_update(update)
                    if self._stopping.is_set():
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info(f"agent event subscription failed device={device_id}: {exc}")
                await asyncio.sleep(1.0)

    async def _apply_agent_update(self, update: FPGAState) -> None:
        async with self._lock:
            self.primary_board = update
        await self._publish_board_updated()

    async def _publish_board_updated(self) -> None:
        event = {"type": "board.updated", "board": self._board_payload()}
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for subscriber in list(self._subscribers):
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(subscriber)
        for subscriber in stale:
            self._subscribers.discard(subscriber)

    def _board_payload(self) -> dict[str, Any]:
        board = self.primary_board
        if board is None:
            return {
                "device_id": None,
                "status": "unavailable",
                "faults": [],
                "telemetry": {"temperature_c": None, "checked_at": None},
                "active_session_id": None,
            }
        return {
            "device_id": board.device_id,
            "status": str(board.status.value if hasattr(board.status, "value") else board.status),
            "faults": [fault.model_dump(mode="json") for fault in board.faults],
            "telemetry": board.telemetry.model_dump(mode="json"),
            "active_session_id": None,
        }