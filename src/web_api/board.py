from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from fpga_agent.fpga import FPGAState, FPGAStatus

from .agent_client import AgentClient
from .sessions import (
    DemoSession,
    SessionEndReason,
    SessionError,
    SessionManager,
    SessionStatus,
)

logger = logging.getLogger("board")


class BoardError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class BoardManager:
    def __init__(
        self,
        agent: AgentClient,
        demos: dict[str, Any],
        sessions: SessionManager | None = None,
    ):
        self.agent = agent
        self.demos = demos
        self.sessions = sessions or SessionManager()

        self.device_id: str | None = None
        self.fpga_state: FPGAState | None = None

        self._running = False
        self._agent_connected = False

        self._watch_task: asyncio.Task | None = None
        self._expiry_task: asyncio.Task | None = None
        self._flow_lock = asyncio.Lock()

        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    @property
    def available(self) -> bool:
        return self.device_id is not None and self.fpga_state is not None and self._agent_connected

    async def start(self) -> None:
        logger.info("starting board manager")
        devices = await self.agent.list_devices()
        if not devices:
            raise RuntimeError("No FPGA devices found")

        self.device_id = devices[0]
        self.fpga_state = await self.agent.get_device(self.device_id)
        self._running = True
        self._agent_connected = True
        logger.info(
            "selected primary board device=%s status=%s faults=%d",
            self.device_id,
            self.fpga_state.status,
            len(self.fpga_state.faults),
        )

        self._watch_task = asyncio.create_task(
            self._watch_agent(),
            name="board-agent-watch",
        )
        if self.fpga_state.status == FPGAStatus.IDLE:
            await self._try_start_next()

    async def stop(self) -> None:
        self._running = False
        self._cancel_expiry()

        if self._watch_task:
            self._watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None

        self._subscribers.clear()

    async def snapshot_for(self, user_id: str) -> dict[str, Any]:
        return {
            "board": self._public_board(),
            "demos": [self._public_demo(demo) for demo in self.demos.values()],
            "queue": (await self.sessions.queue_for_user(user_id)).model_dump(mode="json"),
            "session": _session_json(await self.sessions.session_for_user(user_id)),
        }

    async def subscribe(self, user_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        self._subscribers.setdefault(user_id, set()).add(queue)

        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(user_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(user_id, None)

    async def create_session(self, user_id: str, demo_id: str) -> DemoSession:
        if demo_id not in self.demos:
            raise BoardError("unknown_demo", "Unknown demo.")
        active_before = self.sessions.active

        try:
            session = await self.sessions.create(user_id, demo_id)
        except SessionError as exc:
            raise BoardError(exc.code, str(exc)) from exc
        await self._publish_user(user_id, {
            "type": "session.updated",
            "session": _session_json(session),
        })
        await self._publish_queue_updates()

        active_after = self.sessions.active
        if active_after and (
            active_before is None
            or active_before.expires_at != active_after.expires_at
        ):
            await self._publish_user(active_after.user_id, {
                "type": "session.updated",
                "session": _session_json(active_after),
            })
            self._schedule_expiry(active_after)

        await self._try_start_next()
        return session

    async def end_session(self, user_id: str, session_id: str) -> DemoSession:
        try:
            session, needs_reset = await self.sessions.end_by_user(user_id, session_id)
        except SessionError as exc:
            raise BoardError(exc.code, str(exc)) from exc

        await self._publish_user(user_id, {
            "type": "session.updated",
            "session": _session_json(session),
        })

        if not needs_reset:
            await self._publish_queue_updates()
            return session

        self._cancel_expiry()

        async with self._flow_lock:
            try:
                await self._publish_user(user_id, {
                    "type": "ui.message",
                    "level": "info",
                    "message": "Ending demo...",
                })

                if self.device_id:
                    await self.agent.reset(self.device_id)

            except Exception:
                logger.exception("failed to reset board while ending session")
                await self._publish_user(user_id, {
                    "type": "ui.message",
                    "level": "error",
                    "message": "Board reset failed.",
                })

            ended = await self.sessions.finish_active()

        if ended:
            await self._publish_user(ended.user_id, {
                "type": "session.updated",
                "session": _session_json(ended),
            })

        await self._publish_queue_updates()
        await self._try_start_next()

        return ended or session

    async def _watch_agent(self) -> None:
        assert self.device_id is not None

        while self._running:
            try:
                async for state in self.agent.subscribe(self.device_id):
                    if not self._running:
                        return

                    self._agent_connected = True
                    await self._handle_board_state(state)
            except asyncio.CancelledError:
                raise

            except Exception:
                self._agent_connected = False
                logger.exception("lost FPGA agent event stream")
                await self._broadcast({
                    "type": "ui.message",
                    "level": "error",
                    "message": "Lost connection to FPGA agent.",
                })
                if self._running:
                    await asyncio.sleep(1)

    async def _handle_board_state(self, state: FPGAState) -> None:
        self.fpga_state = state
        await self._broadcast({
            "type": "board.updated",
            "board": self._public_board(),
        })
        if state.status == FPGAStatus.FAULT:
            await self._end_for_board_problem(SessionEndReason.FPGA_FAULT)
            return
        if state.status == FPGAStatus.OFFLINE:
            await self._end_for_board_problem(SessionEndReason.BOARD_OFFLINE)
            return
        if state.status == FPGAStatus.IDLE:
            await self._try_start_next()

    async def _try_start_next(self) -> None:
        if not self._running:
            return

        if not self.fpga_state or self.fpga_state.status != FPGAStatus.IDLE:
            return
        try:
            session = await self.sessions.begin_next()
        except SessionError:
            return
        if session is None:
            return
        await self._publish_user(session.user_id, {
            "type": "session.updated",
            "session": _session_json(session),
        })
        await self._publish_queue_updates()

        demo = self.demos[session.demo_id]
        await self._publish_user(session.user_id, {
            "type": "ui.message",
            "level": "info",
            "message": "Programming FPGA...",
        })
        try:
            await self._program_demo(demo)
        except Exception:
            logger.exception("failed to start demo session=%s", session.id)

            active = self.sessions.active
            if active and active.id == session.id and active.status == SessionStatus.STARTING:
                failed = await self.sessions.fail_start(session.id)

                await self._publish_user(session.user_id, {
                    "type": "session.updated",
                    "session": _session_json(failed),
                })
                await self._publish_user(session.user_id, {
                    "type": "ui.message",
                    "level": "error",
                    "message": "Failed to start demo.",
                })

            return

        # The board may have faulted while programming was in progress.
        active = self.sessions.active
        if not active or active.id != session.id or active.status != SessionStatus.STARTING:
            return

        try:
            session = await self.sessions.activate(session.id)
        except SessionError:
            return

        self._schedule_expiry(session)

        await self._publish_user(session.user_id, {
            "type": "session.updated",
            "session": _session_json(session),
        })
        await self._publish_user(session.user_id, {
            "type": "ui.message",
            "level": "success",
            "message": "Demo ready.",
        })

    async def _program_demo(self, demo: Any) -> None:
        if not self.device_id:
            raise RuntimeError("No FPGA selected")

        bitstream = getattr(demo, "bitstream", None)
        ps7_init_tcl = getattr(demo, "ps7_init_tcl", None)
        elf = getattr(demo, "elf", None)

        if bitstream:
            await self.agent.program_pl(self.device_id, bitstream)

        if ps7_init_tcl or elf:
            if not ps7_init_tcl or not elf:
                raise RuntimeError("PS demo requires both ps7_init_tcl and elf")

            await self.agent.program_ps(
                self.device_id,
                ps7_init_tcl=ps7_init_tcl,
                elf=elf,
            )

    async def _end_for_board_problem(self, reason: SessionEndReason) -> None:
        self._cancel_expiry()

        session = await self.sessions.begin_active_end(reason)
        if session is None:
            return

        await self._publish_user(session.user_id, {
            "type": "session.updated",
            "session": _session_json(session),
        })

        message = (
            "FPGA fault detected. Your session has ended."
            if reason == SessionEndReason.FPGA_FAULT
            else "FPGA became unavailable. Your session has ended."
        )

        await self._publish_user(session.user_id, {
            "type": "ui.message",
            "level": "error",
            "message": message,
        })

        ended = await self.sessions.finish_active()
        if ended:
            await self._publish_user(ended.user_id, {
                "type": "session.updated",
                "session": _session_json(ended),
            })

        # Do not reset here. The FPGA agent owns hardware/fault recovery.
        # The queue resumes when the agent eventually reports IDLE.

    def _schedule_expiry(self, session: DemoSession) -> None:
        self._cancel_expiry()

        if session.expires_at is None:
            return

        self._expiry_task = asyncio.create_task(
            self._expire_session(session.id, session.expires_at),
            name=f"session-expiry-{session.id}",
        )

    async def _expire_session(self, session_id: str, expires_at: datetime) -> None:
        delay = max(0.0, (expires_at - datetime.now(UTC)).total_seconds())

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        active = self.sessions.active
        if (
            not active
            or active.id != session_id
            or active.status != SessionStatus.ACTIVE
            or active.expires_at != expires_at
        ):
            return

        session = await self.sessions.begin_active_end(SessionEndReason.EXPIRED)
        if session is None:
            return

        await self._publish_user(session.user_id, {
            "type": "session.updated",
            "session": _session_json(session),
        })

        await self._publish_user(session.user_id, {
            "type": "ui.message",
            "level": "warning",
            "message": "Your FPGA session has expired.",
        })

        try:
            if self.device_id:
                await self.agent.reset(self.device_id)
        except Exception:
            logger.exception("failed to reset board after session expiry")

        ended = await self.sessions.finish_active()

        if ended:
            await self._publish_user(ended.user_id, {
                "type": "session.updated",
                "session": _session_json(ended),
            })

        self._expiry_task = None
        await self._publish_queue_updates()
        await self._try_start_next()

    def _cancel_expiry(self) -> None:
        task = self._expiry_task
        self._expiry_task = None

        if task and task is not asyncio.current_task():
            task.cancel()

    async def _publish_queue_updates(self) -> None:
        for user_id in list(self._subscribers):
            queue = await self.sessions.queue_for_user(user_id)

            await self._publish_user(user_id, {
                "type": "queue.updated",
                "queue": queue.model_dump(mode="json"),
            })

    async def _broadcast(self, event: dict[str, Any]) -> None:
        for user_id in list(self._subscribers):
            await self._publish_user(user_id, event)

    async def _publish_user(self, user_id: str, event: dict[str, Any]) -> None:
        for queue in self._subscribers.get(user_id, set()).copy():
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()

            queue.put_nowait(event)

    def _public_board(self) -> dict[str, Any] | None:
        if self.fpga_state is None:
            return None

        return {
            "device_id": self.device_id,
            "status": self.fpga_state.status.value,
            "telemetry": self.fpga_state.telemetry.model_dump(mode="json"),
            "faults": [
                fault.model_dump(mode="json")
                for fault in self.fpga_state.faults
            ],
        }

    @staticmethod
    def _public_demo(demo: Any) -> dict[str, Any]:
        result = {
            "id": getattr(demo, "id"),
            "name": getattr(demo, "name"),
        }

        description = getattr(demo, "description", None)
        if description is not None:
            result["description"] = description

        return result


def _session_json(session: DemoSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    data = session.model_dump(mode="json")
    data.pop("user_id", None)

    if session.status == SessionStatus.ACTIVE:
        data["demo_url"] = f"/api/sessions/{session.id}/demo/"
    else:
        data["demo_url"] = None
    return data