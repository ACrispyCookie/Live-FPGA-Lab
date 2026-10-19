from __future__ import annotations

import asyncio
from types import SimpleNamespace

from web_api.board import BoardManager
from web_api.config import SessionConfig, WebApiConfig
from web_api.sessions import SessionEndReason, SessionManager, SessionStatus


def test_periodic_demo_http_presence_prevents_disconnect_timeout():
    async def scenario():
        config = WebApiConfig(session=SessionConfig(disconnected_session_timeout_seconds=0.1))
        sessions = SessionManager(config.session)
        board = BoardManager(SimpleNamespace(reset=lambda *_: None), config=config, demos={}, sessions=sessions)
        session = await sessions.create("owner", "dvd-logo-video")
        await sessions.begin_next()
        await sessions.activate(session.id)
        # The HTML page and WebRTC signaling are finite proxied requests.
        await board.demo_connection_opened("owner", session.id)
        await board.demo_connection_closed("owner", session.id)
        for _ in range(4):
            await asyncio.sleep(0.04)
            await board.demo_connection_opened("owner", session.id)
            await board.demo_connection_closed("owner", session.id)
            assert sessions.active is not None
            assert sessions.active.status == SessionStatus.ACTIVE
        await asyncio.sleep(0.14)
        assert sessions.active is None
        ended = await sessions.get(session.id)
        assert ended.end_reason == SessionEndReason.TIMED_OUT
        await board.stop()

    asyncio.run(scenario())
