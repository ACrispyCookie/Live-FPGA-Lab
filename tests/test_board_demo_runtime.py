from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from fpga_agent.fpga import FPGAStatus
from web_api.board import BoardError, BoardManager
from web_api.demo_loader import DemoDefinition
from web_api.sessions import SessionManager, SessionStatus


class FakeAgent:
    def __init__(self) -> None:
        self.reset_calls: list[str] = []

    async def reset(self, device_id: str) -> Any:
        self.reset_calls.append(device_id)
        return SimpleNamespace(status=FPGAStatus.IDLE)


def run(coro):
    return asyncio.run(coro)


def make_demo(stopped: list[str]) -> DemoDefinition:
    def start_session(*, demo, session_id: str):
        return {
            "backend": "http://127.0.0.1:4567",
            "handle": f"runtime-{session_id}",
        }

    def stop_session(runtime):
        stopped.append(runtime["session_id"])

    return DemoDefinition(
        id="demo",
        name="Demo",
        root=Path.cwd(),
        start_session=start_session,
        stop_session=stop_session,
    )


async def active_session(sessions: SessionManager):
    queued = await sessions.create("owner", "demo")
    starting = await sessions.begin_next()
    assert starting is not None
    assert starting.id == queued.id
    return await sessions.activate(starting.id)


def test_demo_backend_requires_active_owner_and_runtime() -> None:
    async def scenario():
        stopped: list[str] = []
        demo = make_demo(stopped)
        sessions = SessionManager()
        board = BoardManager(cast(Any, FakeAgent()), demos={"demo": demo}, sessions=sessions)
        session = await active_session(sessions)

        await board._start_demo_runtime(demo, session)

        assert await board.demo_backend_for("owner", session.id) == "http://127.0.0.1:4567"

        with pytest.raises(BoardError) as exc:
            await board.demo_backend_for("other-user", session.id)
        assert exc.value.code == "session_not_owned"
        assert exc.value.status_code == 403

        await board._stop_demo_runtime()
        assert stopped == [session.id]

        with pytest.raises(BoardError) as exc:
            await board.demo_backend_for("owner", session.id)
        assert exc.value.code == "demo_unavailable"
        assert exc.value.status_code == 503

    run(scenario())


def test_end_session_stops_runtime_before_finishing_session() -> None:
    async def scenario():
        stopped: list[str] = []
        demo = make_demo(stopped)
        sessions = SessionManager()
        agent = FakeAgent()
        board = BoardManager(cast(Any, agent), demos={"demo": demo}, sessions=sessions)
        board.device_id = "board-1"
        session = await active_session(sessions)
        await board._start_demo_runtime(demo, session)

        ended = await board.end_session("owner", session.id)

        assert ended.status == SessionStatus.ENDED
        assert stopped == [session.id]
        assert board._demo_runtime is None
        assert agent.reset_calls == ["board-1"]

    run(scenario())


def test_start_failure_resets_board_and_promotes_next_session() -> None:
    async def scenario():
        sessions = SessionManager()
        agent = FakeAgent()
        starts: list[str] = []

        def start_session(*, demo, session_id: str):
            starts.append(session_id)
            if len(starts) == 1:
                raise RuntimeError("demo runtime failed")
            return {"backend": "http://127.0.0.1:4567"}

        demo = DemoDefinition(
            id="demo",
            name="Demo",
            root=Path.cwd(),
            start_session=start_session,
        )
        board = BoardManager(cast(Any, agent), demos={"demo": demo}, sessions=sessions)
        board.device_id = "board-1"
        board.fpga_state = cast(Any, SimpleNamespace(status=FPGAStatus.IDLE))
        board._running = True

        first = await sessions.create("first", "demo")
        second = await sessions.create("second", "demo")

        await board._try_start_next()

        assert (await sessions.get(first.id)).status == SessionStatus.ENDED
        assert (await sessions.get(second.id)).status == SessionStatus.ACTIVE
        assert agent.reset_calls == ["board-1"]
        assert board._demo_runtime is not None
        assert board._demo_runtime["session_id"] == second.id

    run(scenario())
