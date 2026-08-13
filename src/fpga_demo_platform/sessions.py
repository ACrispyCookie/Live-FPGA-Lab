from __future__ import annotations

import json
import mimetypes
import queue
import shutil
import sqlite3
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fpga_demo_platform.demos import get_demo, get_project
from fpga_demo_platform.thermal import HardwareUnavailable, ThermalGuard

SessionState = Literal["queued", "starting", "active", "releasing", "released", "expired", "cancelled", "failed"]
TERMINAL_STATES = {"released", "expired", "cancelled", "failed"}
DEFAULT_LEASE_SECONDS = 180
DEFAULT_IDLE_TIMEOUT_SECONDS = 45
DEFAULT_EXTENSION_SECONDS = 60
DEFAULT_MAX_TOTAL_SECONDS = 300
DEFAULT_HISTORY_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_MAX_FINISHED_SESSIONS = 200


@dataclass(frozen=True)
class Artifact:
    name: str
    kind: str
    path: str
    content_type: str


@dataclass(frozen=True)
class Session:
    id: str
    project_id: str
    demo_id: str
    state: SessionState
    requester: str | None
    queue_position: int | None
    created_at: str
    lease_started_at: str | None
    lease_expires_at: str | None
    released_at: str | None
    error: str | None
    artifact_dir: str | None


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any]
    sequence: int


class EventBus:
    def __init__(self, *, backlog_size: int = 200, subscriber_queue_size: int = 100):
        self.subscriber_queue_size = subscriber_queue_size
        self._lock = threading.Lock()
        self._sequence = 0
        self._backlog: deque[Event] = deque(maxlen=backlog_size)
        self._subscribers: list[queue.Queue[Event]] = []

    def publish(self, event_type: str, payload: dict[str, Any]) -> Event:
        with self._lock:
            self._sequence += 1
            event = Event(event_type, payload, self._sequence)
            self._backlog.append(event)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(event)
                except queue.Full:
                    pass
        return event

    def subscribe(self) -> queue.Queue[Event]:
        subscriber: queue.Queue[Event] = queue.Queue(maxsize=self.subscriber_queue_size)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[Event]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)


class SessionManager:
    def __init__(self, db_path: str | Path, artifacts_dir: str | Path, *, thermal_guard: ThermalGuard | None = None, event_bus: EventBus | None = None):
        self.db_path = Path(db_path)
        self.artifacts_dir = Path(artifacts_dir)
        self.thermal_guard = thermal_guard or ThermalGuard()
        self.event_bus = event_bus or EventBus()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.purge_history()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    demo_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    requester TEXT,
                    created_at TEXT NOT NULL,
                    lease_started_at TEXT,
                    lease_expires_at TEXT,
                    released_at TEXT,
                    error TEXT,
                    artifact_dir TEXT
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "project_id" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN project_id TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    PRIMARY KEY (session_id, name)
                )
            """)

    def request_session(self, project_id: str, *, requester: str | None = None) -> Session:
        self.purge_history()
        project = get_project(project_id)
        if not project.runnable or project.demo_id is None:
            raise ValueError(f"project '{project_id}' is not runnable on the FPGA demo platform")
        demo_id = project.demo_id
        demo = get_demo(demo_id)
        if not demo.available:
            raise ValueError(f"project '{project_id}' is not available")
        try:
            self.thermal_guard.assert_available()
        except HardwareUnavailable:
            raise
        session_id = f"sess_{uuid.uuid4().hex[:16]}"
        now = _now()
        artifact_dir = self.artifacts_dir / session_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if requester:
                existing = conn.execute(
                    "SELECT id FROM sessions WHERE requester = ? AND state IN ('queued', 'starting', 'active', 'releasing') LIMIT 1",
                    (requester,),
                ).fetchone()
                if existing is not None:
                    raise SessionLimitExceeded("requester already has an active or queued FPGA session")
            active = conn.execute("SELECT id FROM sessions WHERE state IN ('starting', 'active', 'releasing') LIMIT 1").fetchone()
            state = "queued" if active else "active"
            starts = now if state == "active" else None
            expires = _iso(datetime.now(UTC) + timedelta(seconds=DEFAULT_LEASE_SECONDS)) if state == "active" else None
            conn.execute(
                """
                INSERT INTO sessions (id, project_id, demo_id, state, requester, created_at, lease_started_at, lease_expires_at, artifact_dir)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, project_id, demo_id, state, requester, now, starts, expires, str(artifact_dir)),
            )
        session = self.get(session_id)
        self.event_bus.publish("session.created", {"session": session_to_dict(session)})
        self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
        self.event_bus.publish("board.status", self.board_status())
        return session

    def get(self, session_id: str) -> Session:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown session '{session_id}'")
        return self._session_from_row(row)

    def list_recent(self, *, limit: int = 20, state: str | None = None) -> list[Session]:
        self.purge_history()
        with self._connect() as conn:
            if state:
                rows = conn.execute("SELECT * FROM sessions WHERE state = ? ORDER BY created_at DESC LIMIT ?", (state, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._session_from_row(row) for row in rows]

    def release(self, session_id: str) -> Session:
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown session '{session_id}'")
            if row["state"] == "queued":
                new_state = "cancelled"
            elif row["state"] in TERMINAL_STATES:
                new_state = row["state"]
            else:
                new_state = "released"
            conn.execute("UPDATE sessions SET state = ?, released_at = ? WHERE id = ?", (new_state, now, session_id))
            if row["state"] in {"active", "starting", "releasing"}:
                self._promote_next_locked(conn)
        session = self.get(session_id)
        self.event_bus.publish("session.finished", {"session": session_to_dict(session)})
        self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
        self.event_bus.publish("board.status", self.board_status())
        self.purge_history()
        return session

    def extend(self, session_id: str) -> Session:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown session '{session_id}'")
            if row["state"] != "active":
                raise ValueError("only active sessions can be extended")
            waiting = conn.execute("SELECT id FROM sessions WHERE state = 'queued' LIMIT 1").fetchone()
            if waiting is not None:
                raise ValueError("another user is waiting for the FPGA")
            current_expiry = datetime.fromisoformat(row["lease_expires_at"])
            max_expiry = datetime.fromisoformat(row["lease_started_at"]) + timedelta(seconds=DEFAULT_MAX_TOTAL_SECONDS)
            new_expiry = min(current_expiry + timedelta(seconds=DEFAULT_EXTENSION_SECONDS), max_expiry)
            if new_expiry <= current_expiry:
                raise ValueError("session is already at maximum duration")
            conn.execute("UPDATE sessions SET lease_expires_at = ? WHERE id = ?", (_iso(new_expiry), session_id))
        session = self.get(session_id)
        self.event_bus.publish("session.updated", {"session": session_to_dict(session)})
        return session

    def publish_artifact(self, session_id: str, name: str, kind: str, content: str | bytes, *, content_type: str | None = None) -> Artifact:
        safe_name = _safe_artifact_name(name)
        session = self.get(session_id)
        artifact_dir = Path(session.artifact_dir or self.artifacts_dir / session_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / safe_name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        detected = content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO artifacts (session_id, name, kind, path, content_type) VALUES (?, ?, ?, ?, ?)",
                (session_id, safe_name, kind, str(path), detected),
            )
        artifact = Artifact(safe_name, kind, str(path), detected)
        self.event_bus.publish("artifact.created", {"session_id": session_id, "artifact": artifact_to_dict(session_id, artifact)})
        return artifact

    def get_artifact(self, session_id: str, name: str) -> Artifact:
        safe_name = _safe_artifact_name(name)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE session_id = ? AND name = ?", (session_id, safe_name)).fetchone()
        if row is None:
            raise KeyError(f"unknown artifact '{name}'")
        return Artifact(row["name"], row["kind"], row["path"], row["content_type"])

    def queue_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            queued = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE state = 'queued'").fetchone()["n"]
            active = conn.execute("SELECT id FROM sessions WHERE state IN ('starting', 'active', 'releasing') ORDER BY created_at ASC LIMIT 1").fetchone()
            next_row = conn.execute("SELECT id FROM sessions WHERE state = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
        return {"queued": queued, "active_session_id": active["id"] if active else None, "next_session_id": next_row["id"] if next_row else None}

    def board_status(self) -> dict[str, Any]:
        thermal = self.thermal_guard.snapshot().to_dict()
        summary = self.queue_summary()
        locked = summary["active_session_id"]
        return {
            "board": {"available": thermal.get("available") is True and locked is None, "mode": "leased" if locked else "idle", "locked_by_session_id": locked},
            "thermal": {**thermal, "stale": True},
        }

    def status_snapshot(self) -> dict[str, Any]:
        state = self.board_status()
        return {"api": {"status": "ok"}, **state, "sessions": {"active_session_id": state["board"]["locked_by_session_id"], "queued": self.queue_summary()["queued"]}}

    def artifacts_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM artifacts WHERE session_id = ? ORDER BY name", (session_id,)).fetchall()
        return [artifact_to_dict(session_id, Artifact(row["name"], row["kind"], row["path"], row["content_type"])) for row in rows]

    def purge_history(
        self,
        *,
        retention_seconds: int = DEFAULT_HISTORY_RETENTION_SECONDS,
        max_finished: int = DEFAULT_MAX_FINISHED_SESSIONS,
    ) -> int:
        cutoff = _iso(datetime.now(UTC) - timedelta(seconds=retention_seconds))
        terminal = tuple(TERMINAL_STATES)
        placeholders = ",".join("?" for _ in terminal)
        with self._connect() as conn:
            old_rows = conn.execute(
                f"""
                SELECT id, artifact_dir FROM sessions
                WHERE state IN ({placeholders})
                  AND COALESCE(released_at, lease_expires_at, created_at) < ?
                """,
                (*terminal, cutoff),
            ).fetchall()
            overflow_rows = conn.execute(
                f"""
                SELECT id, artifact_dir FROM sessions
                WHERE state IN ({placeholders})
                ORDER BY COALESCE(released_at, lease_expires_at, created_at) DESC
                LIMIT -1 OFFSET ?
                """,
                (*terminal, max_finished),
            ).fetchall()
            ids: list[str] = []
            artifact_dirs: list[str] = []
            seen: set[str] = set()
            for row in [*old_rows, *overflow_rows]:
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                ids.append(row["id"])
                if row["artifact_dir"]:
                    artifact_dirs.append(row["artifact_dir"])
            if not ids:
                return 0
            id_placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM artifacts WHERE session_id IN ({id_placeholders})", ids)
            conn.execute(f"DELETE FROM sessions WHERE id IN ({id_placeholders})", ids)
        for artifact_dir in artifact_dirs:
            self._remove_artifact_dir(artifact_dir)
        return len(ids)

    def _promote_next_locked(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT id FROM sessions WHERE state = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
        if row is None:
            return
        now_dt = datetime.now(UTC)
        conn.execute(
            "UPDATE sessions SET state = 'active', lease_started_at = ?, lease_expires_at = ? WHERE id = ?",
            (_iso(now_dt), _iso(now_dt + timedelta(seconds=DEFAULT_LEASE_SECONDS)), row["id"]),
        )

    def _remove_artifact_dir(self, artifact_dir: str) -> None:
        path = Path(artifact_dir).resolve()
        root = self.artifacts_dir.resolve()
        if path == root or root not in path.parents:
            return
        shutil.rmtree(path, ignore_errors=True)

    def _session_from_row(self, row: sqlite3.Row) -> Session:
        session_id = row["id"]
        position = None
        if row["state"] == "queued":
            with self._connect() as conn:
                earlier = conn.execute(
                    "SELECT COUNT(*) AS n FROM sessions WHERE state = 'queued' AND created_at <= ?",
                    (row["created_at"],),
                ).fetchone()["n"]
            position = int(earlier)
        project_id = row["project_id"] or f"ece338-{row['demo_id']}"
        return Session(
            id=session_id,
            project_id=project_id,
            demo_id=row["demo_id"],
            state=row["state"],
            requester=row["requester"],
            queue_position=position,
            created_at=row["created_at"],
            lease_started_at=row["lease_started_at"],
            lease_expires_at=row["lease_expires_at"],
            released_at=row["released_at"],
            error=row["error"],
            artifact_dir=row["artifact_dir"],
        )


def session_to_dict(session: Session, *, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    lease = None
    if session.lease_started_at and session.lease_expires_at:
        remaining = max(0, int((datetime.fromisoformat(session.lease_expires_at) - datetime.now(UTC)).total_seconds()))
        lease = {"starts_at": session.lease_started_at, "expires_at": session.lease_expires_at, "remaining_seconds": remaining, "duration_seconds": DEFAULT_LEASE_SECONDS}
    return {
        "id": session.id,
        "project_id": session.project_id,
        "state": session.state,
        "queue_position": session.queue_position,
        "lease": lease,
        "access": {"url": f"/projects/{session.project_id}/session/{session.id}/", "token_required": True} if session.state == "active" else None,
        "created_at": session.created_at,
        "released_at": session.released_at,
        "artifacts": artifacts or [],
        "error": session.error,
    }


def artifact_to_dict(session_id: str, artifact: Artifact) -> dict[str, Any]:
    return {"name": artifact.name, "kind": artifact.kind, "url": f"/api/sessions/{session_id}/artifacts/{artifact.name}", "content_type": artifact.content_type}


def _safe_artifact_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name in {".", ".."} or ".." in Path(name).parts:
        raise ValueError("invalid artifact name")
    return name


class SessionLimitExceeded(RuntimeError):
    pass


def _now() -> str:
    return _iso(datetime.now(UTC))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
