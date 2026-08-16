from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from web_api.config import SessionConfig
from web_api.sessions import SessionManager


def test_active_session_gets_owed_time_when_another_user_arrives(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr("web_api.sessions._now", lambda: now)
    manager = SessionManager(SessionConfig(contended_session_seconds=300, handoff_seconds=60))

    first = asyncio.run(manager.create("user-1", "demo"))
    asyncio.run(manager.begin_next())
    asyncio.run(manager.activate(first.id))

    now += timedelta(seconds=30)
    asyncio.run(manager.create("user-2", "demo"))

    active = manager.active
    assert active is not None
    assert active.expires_at == datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=300)


def test_active_session_gets_contended_period_when_already_past_owed_time(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr("web_api.sessions._now", lambda: now)
    manager = SessionManager(SessionConfig(contended_session_seconds=300, handoff_seconds=60))

    first = asyncio.run(manager.create("user-1", "demo"))
    asyncio.run(manager.begin_next())
    asyncio.run(manager.activate(first.id))

    now += timedelta(seconds=600)
    asyncio.run(manager.create("user-2", "demo"))

    active = manager.active
    assert active is not None
    assert active.expires_at == now + timedelta(seconds=300)
