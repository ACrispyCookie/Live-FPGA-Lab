from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from fpga_agent.fpga import FPGAState, FPGAStatus, JTAGTargetContext
from web_api.board import BoardError, BoardManager
from web_api.demo_loader import DemoDefinition
from web_api.sessions import SessionManager


class FakeAgent:
    async def list_devices(self) -> list[str]:
        return ["board-1"]


def fpga_state(*, reserved_for_projects: bool) -> FPGAState:
    return FPGAState(
        target_ctx=JTAGTargetContext(
            cable_serial="board-1",
            fpga_ctx="fpga",
            fpga_name="xc7z020",
            processor_ctx="cpu",
        ),
        reserved_for_projects=reserved_for_projects,
    )


def test_reserved_for_projects_blocks_agent_programming() -> None:
    state = fpga_state(reserved_for_projects=True)

    assert state.status == FPGAStatus.RESERVED_FOR_PROJECTS
    assert not state.can_program()


def test_public_board_payload_exposes_reserved_for_projects() -> None:
    board = BoardManager(cast(Any, FakeAgent()), sessions=SessionManager())
    board.device_id = "board-1"
    board.fpga_state = fpga_state(reserved_for_projects=True)

    payload = board._public_board()

    assert payload is not None
    assert payload["status"] == "reserved_for_projects"
    assert payload["reserved_for_projects"] is True


def test_reserved_for_projects_rejects_session_creation() -> None:
    async def scenario() -> None:
        demo = DemoDefinition(
            id="demo",
            name="Demo",
            description=None,
            root=Path("."),
        )
        board = BoardManager(
            cast(Any, FakeAgent()),
            demos={"demo": demo},
            sessions=SessionManager(),
        )
        board.device_id = "board-1"
        board.fpga_state = fpga_state(reserved_for_projects=True)

        try:
            await board.create_session("user", "demo")
        except BoardError as exc:
            assert exc.code == "reserved_for_projects"
            assert exc.status_code == 503
        else:
            raise AssertionError("reserved board accepted a session")

    asyncio.run(scenario())
