from __future__ import annotations

import asyncio
import secrets
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import BaseModel


class SessionStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    ACTIVE = "active"
    ENDING = "ending"
    ENDED = "ended"


class SessionEndReason(str, Enum):
    USER_ENDED = "user_ended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FPGA_FAULT = "fpga_fault"


class DemoSession(BaseModel):
    id: str
    user_id: str
    demo_id: str
    status: SessionStatus = SessionStatus.QUEUED

    created_at: datetime
    started_at: datetime | None = None
    expires_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: SessionEndReason | None = None


class QueueState(BaseModel):
    length: int
    position: int | None


@dataclass(frozen=True)
class SessionConfig:
    contended_session_seconds: int = 5 * 60
    handoff_seconds: int = 1 * 60


class SessionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SessionManager:
    def __init__(self, config: SessionConfig | None = None):
        self.config = config or SessionConfig()

        self._sessions: dict[str, DemoSession] = {}
        self._queue: deque[str] = deque()
        self._active_id: str | None = None

        self._lock = asyncio.Lock()

    @property
    def active(self) -> DemoSession | None:
        if self._active_id is None:
            return None

        session = self._sessions.get(self._active_id)
        return session.model_copy(deep=True) if session else None

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    async def create(self, user_id: str, demo_id: str) -> DemoSession:
        async with self._lock:
            if self._live_session_for_user(user_id):
                raise SessionError("session_exists", "You already have a queued or active session.")
            
            session = DemoSession(
                id=secrets.token_urlsafe(16),
                user_id=user_id,
                demo_id=demo_id,
                created_at=_now(),
            )
            self._sessions[session.id] = session
            self._queue.append(session.id)

            # Someone just started waiting while the board is in use.
            # Give the active user their handoff grace period.
            active = self._active()
            if (active
                and active.status == SessionStatus.ACTIVE
                and active.expires_at is None
            ):
                active = active.model_copy(update={
                    "expires_at": _now() + timedelta(
                        seconds=self.config.handoff_seconds,
                    ),
                })
                self._sessions[active.id] = active
            return session.model_copy(deep=True)

    async def begin_next(self) -> DemoSession | None:
        """Move the first queued session into STARTING."""
        async with self._lock:
            if self._active_id is not None or not self._queue:
                return None

            session_id = self._queue.popleft()
            session = self._sessions[session_id].model_copy(update={
                "status": SessionStatus.STARTING,
            })

            self._sessions[session_id] = session
            self._active_id = session_id

            return session.model_copy(deep=True)

    async def activate(self, session_id: str) -> DemoSession:
        """Called by BoardManager after programming succeeds."""
        async with self._lock:
            session = self._require_active(session_id)

            if session.status != SessionStatus.STARTING:
                raise SessionError("invalid_session_state", "Session is not starting.")

            # If somebody is already waiting when the demo starts,
            # this session is immediately time-limited.
            started_at = _now()
            expires_at = None
            if self._queue:
                expires_at = started_at + timedelta(
                    seconds=self.config.contended_session_seconds,
                )

            session = session.model_copy(update={
                "status": SessionStatus.ACTIVE,
                "started_at": started_at,
                "expires_at": expires_at,
            })
            self._sessions[session.id] = session
            return session.model_copy(deep=True)

    async def fail_start(self, session_id: str) -> DemoSession:
        """Called when FPGA/demo programming fails."""
        async with self._lock:
            session = self._require_active(session_id)
            session = session.model_copy(update={
                "status": SessionStatus.ENDED,
                "ended_at": _now(),
                "end_reason": SessionEndReason.PROGRAMMING_FAILED,
            })

            self._sessions[session.id] = session
            self._active_id = None
            return session.model_copy(deep=True)

    async def end_by_user(
        self,
        user_id: str,
        session_id: str,
    ) -> tuple[DemoSession, bool]:
        """
        End the user's session.
        Returns (session, needs_board_reset).
        Queued sessions end immediately.
        Active/starting sessions move to ENDING and need BoardManager to reset.
        """
        async with self._lock:
            session = self._require(session_id)
            if session.user_id != user_id:
                raise SessionError("session_not_owned", "Session does not belong to this user.")

            if session.status == SessionStatus.QUEUED:
                self._remove_from_queue(session.id)
                session = session.model_copy(update={
                    "status": SessionStatus.ENDED,
                    "ended_at": _now(),
                    "end_reason": SessionEndReason.CANCELLED,
                })
                self._sessions[session.id] = session
                return session.model_copy(deep=True), False

            if session.id != self._active_id:
                raise SessionError("invalid_session_state", "Session cannot be ended.")
            if session.status not in {SessionStatus.STARTING, SessionStatus.ACTIVE}:
                raise SessionError("invalid_session_state", "Session cannot be ended.")

            session = session.model_copy(update={
                "status": SessionStatus.ENDING,
                "end_reason": SessionEndReason.USER_ENDED,
            })
            self._sessions[session.id] = session
            return session.model_copy(deep=True), True

    async def begin_active_end(
        self,
        reason: SessionEndReason,
    ) -> DemoSession | None:
        """End the active session because of expiry/fault/offline state."""
        async with self._lock:
            session = self._active()
            if session is None:
                return None
            if session.status == SessionStatus.ENDING:
                return session.model_copy(deep=True)
            
            session = session.model_copy(update={
                "status": SessionStatus.ENDING,
                "end_reason": reason,
            })
            self._sessions[session.id] = session
            return session.model_copy(deep=True)

    async def finish_active(self) -> DemoSession | None:
        """Called after BoardManager has finished resetting the board."""
        async with self._lock:
            session = self._active()
            if session is None:
                return None

            session = session.model_copy(update={
                "status": SessionStatus.ENDED,
                "ended_at": _now(),
            })
            self._sessions[session.id] = session
            self._active_id = None
            return session.model_copy(deep=True)

    async def get(self, session_id: str) -> DemoSession:
        async with self._lock:
            return self._require(session_id).model_copy(deep=True)

    async def session_for_user(self, user_id: str) -> DemoSession | None:
        async with self._lock:
            session = self._live_session_for_user(user_id)
            return session.model_copy(deep=True) if session else None

    async def queue_for_user(self, user_id: str) -> QueueState:
        async with self._lock:
            position = None

            for index, session_id in enumerate(self._queue, start=1):
                if self._sessions[session_id].user_id == user_id:
                    position = index
                    break

            return QueueState(
                length=len(self._queue),
                position=position,
            )

    async def queued_sessions(self) -> list[DemoSession]:
        async with self._lock:
            return [
                self._sessions[session_id].model_copy(deep=True)
                for session_id in self._queue
            ]

    def _active(self) -> DemoSession | None:
        if self._active_id is None:
            return None
        return self._sessions.get(self._active_id)

    def _live_session_for_user(self, user_id: str) -> DemoSession | None:
        for session in self._sessions.values():
            if (
                session.user_id == user_id
                and session.status != SessionStatus.ENDED
            ):
                return session
        return None

    def _require(self, session_id: str) -> DemoSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError(
                "session_not_found",
                "Session does not exist.",
            )
        return session

    def _require_active(self, session_id: str) -> DemoSession:
        session = self._require(session_id)

        if self._active_id != session_id:
            raise SessionError(
                "invalid_session_state",
                "Session is not the active session.",
            )

        return session

    def _remove_from_queue(self, session_id: str) -> None:
        try:
            self._queue.remove(session_id)
        except ValueError:
            pass


def _now() -> datetime:
    return datetime.now(UTC)