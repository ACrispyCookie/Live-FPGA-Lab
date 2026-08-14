from __future__ import annotations

import json
import mimetypes
import queue
import secrets
import shutil
import sqlite3
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fpga_demo_platform.demos import get_demo, get_project, start_demo_session, stop_demo_session
from fpga_demo_platform.thermal import BoardWiper, HardwareUnavailable, ThermalGuard

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
    owner_token: str | None = None


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any]
    sequence: int
    time: str


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
            event = Event(event_type, payload, self._sequence, _now())
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

    def backlog(self) -> list[Event]:
        with self._lock:
            return list(self._backlog)


class SessionManager:
    def __init__(self, db_path: str | Path, artifacts_dir: str | Path, *, thermal_guard: ThermalGuard | None = None, event_bus: EventBus | None = None, board_wiper: BoardWiper | None = None):
        self.db_path = Path(db_path)
        self.artifacts_dir = Path(artifacts_dir)
        self.thermal_guard = thermal_guard or ThermalGuard()
        self.event_bus = event_bus or EventBus()
        self.board_wiper = board_wiper or BoardWiper()
        self._runtimes: dict[str, dict[str, Any]] = {}
        self._logs: dict[str, list[dict[str, Any]]] = {}
        self._expiry_warned: dict[str, set[int]] = {}
        self._board_unavailable = False
        self._last_board_status_event_key: str | None = None
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.purge_history()

    def start_board_monitor(self, *, interval_seconds: float = 15.0) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=self._board_monitor_loop, args=(interval_seconds,), daemon=True)
        self._monitor_thread.start()

    def stop_board_monitor(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

    def _board_monitor_loop(self, interval_seconds: float) -> None:
        while not self._monitor_stop.wait(interval_seconds):
            try:
                self.check_board_safety()
            except Exception as exc:
                self.event_bus.publish("safety.monitor_error", {"error": str(exc)})

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
                    artifact_dir TEXT,
                    owner_token TEXT
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "project_id" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN project_id TEXT")
            if "owner_token" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN owner_token TEXT")
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
        owner_token = secrets.token_urlsafe(32)
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
            state = "queued" if active else "starting"
            starts = now if state == "starting" else None
            expires = _iso(datetime.now(UTC) + timedelta(seconds=DEFAULT_LEASE_SECONDS)) if state == "starting" else None
            conn.execute(
                """
                INSERT INTO sessions (id, project_id, demo_id, state, requester, created_at, lease_started_at, lease_expires_at, artifact_dir, owner_token)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, project_id, demo_id, state, requester, now, starts, expires, str(artifact_dir), owner_token),
            )
        session = self.get(session_id)
        self._record_session_log(session, "session", "stdout", f"session requested; initial state is {session.state}")
        self.event_bus.publish("session.created", {"session": session_to_dict(session)})
        self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
        self._publish_board_status(force=True)
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
        self._cleanup_runtime(session_id)
        now = _now()
        should_wipe = False
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
                should_wipe = True
            conn.execute("UPDATE sessions SET state = ?, released_at = ? WHERE id = ?", (new_state, now, session_id))
            if row["state"] in {"active", "starting", "releasing"} and self.thermal_guard.snapshot().available:
                self._promote_next_locked(conn)
        session = self.get(session_id)
        if should_wipe:
            wipe_result = self.board_wiper.wipe()
            self.event_bus.publish("safety.wipe", {"session_id": session_id, "reason": "session_released", "wipe": wipe_result})
        self._start_current_starting_session(ignore_errors=True)
        self.event_bus.publish("session.finished", {"session": session_to_dict(session)})
        self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
        self._publish_board_status(force=True)
        self.purge_history()
        return session

    def require_owner(self, session_id: str, owner_token: str | None) -> Session:
        session = self.get(session_id)
        if not owner_token or not secrets.compare_digest(owner_token, session.owner_token or ""):
            raise PermissionError("session owner token is required")
        return session

    def cancel_if_queued(self, session_id: str, *, reason: str = "owner_disconnected") -> Session | None:
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None or row["state"] != "queued":
                return None
            conn.execute("UPDATE sessions SET state = 'cancelled', released_at = ?, error = ? WHERE id = ?", (now, reason, session_id))
        session = self.get(session_id)
        self.event_bus.publish("session.finished", {"session": session_to_dict(session)})
        self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
        self._publish_board_status(force=True)
        return session

    def start_session_ignore_errors(self, session_id: str) -> None:
        try:
            self.start_session(session_id)
        except SessionStartFailed:
            pass

    def start_session(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session.state != "starting":
            raise ValueError(f"session must be starting before demo startup, not {session.state}")
        demo = get_demo(session.demo_id)
        artifact_dir = Path(session.artifact_dir or self.artifacts_dir / session_id)

        def emit_log(phase: str, stream: str, message: str) -> None:
            self._record_session_log(session, phase, stream, message)

        emit_log("session", "stdout", "session starting; preparing exclusive FPGA lease")
        self.event_bus.publish("session.starting", {"session": session_to_dict(session)})
        try:
            emit_log("program_board", "stdout", "pausing thermal reader while programming uses JTAG")
            stop_thermal = getattr(self.thermal_guard, "stop", None)
            if stop_thermal is not None:
                stop_thermal()
            runtime = start_demo_session(demo, session_id=session_id, artifact_dir=artifact_dir, emit_log=emit_log)
            self._runtimes[session_id] = runtime
            access_url = str(runtime.get("access_url") or f"/api/sessions/{session_id}/demo/")
            with self._connect() as conn:
                conn.execute("UPDATE sessions SET state = 'active' WHERE id = ? AND state = 'starting'", (session_id,))
            ready = self.get(session_id)
            self.event_bus.publish("session.ready", {"session": session_to_dict(ready), "access": {"url": access_url, "token_required": True}})
            self.event_bus.publish("session.updated", {"session": session_to_dict(ready)})
            return ready
        except Exception as exc:
            self._record_session_log_once(session, "program_board", "stderr", str(exc))
            self._cleanup_runtime(session_id)
            wipe_result = self.board_wiper.wipe()
            self.event_bus.publish("safety.wipe", {"session_id": session_id, "reason": "session_failed", "wipe": wipe_result})
            with self._connect() as conn:
                conn.execute("UPDATE sessions SET state = 'failed', released_at = ?, error = ? WHERE id = ?", (_now(), str(exc), session_id))
            failed = self.get(session_id)
            self.event_bus.publish("session.failed", {"session": session_to_dict(failed), "error": str(exc)})
            self.event_bus.publish("session.finished", {"session": session_to_dict(failed)})
            raise SessionStartFailed(session_id, str(exc)) from exc

    def runtime_for_session(self, session_id: str, owner_token: str | None) -> dict[str, Any]:
        session = self.require_owner(session_id, owner_token)
        if session.state != "active" or session_id not in self._runtimes:
            raise ValueError("session demo is not active")
        return self._runtimes[session_id]

    def logs_for_session(self, session_id: str) -> list[dict[str, Any]]:
        try:
            session = self.get(session_id)
        except KeyError:
            return list(self._logs.get(session_id, []))
        artifact_dir = Path(session.artifact_dir or self.artifacts_dir / session_id)
        log_path = artifact_dir / "session-events.jsonl"
        if not log_path.exists():
            return list(self._logs.get(session_id, []))
        logs: list[dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                logs.append(item)
        return logs

    def _record_session_log(self, session: Session, phase: str, stream: str, message: str) -> dict[str, Any]:
        entry = {"time": _now(), "phase": phase, "stream": stream, "message": message}
        self._logs.setdefault(session.id, []).append(entry)
        artifact_dir = Path(session.artifact_dir or self.artifacts_dir / session.id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "session-events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO artifacts (session_id, name, kind, path, content_type) VALUES (?, ?, ?, ?, ?)",
                (session.id, "session-events.jsonl", "log", str(path), "application/x-ndjson"),
            )
        self.event_bus.publish("session.log", {"session_id": session.id, **entry})
        return entry

    def _record_session_log_once(self, session: Session, phase: str, stream: str, message: str) -> dict[str, Any] | None:
        for entry in self.logs_for_session(session.id):
            if entry.get("stream") == stream and entry.get("message") == message:
                return None
        return self._record_session_log(session, phase, stream, message)

    def _cleanup_runtime(self, session_id: str) -> None:
        runtime = self._runtimes.pop(session_id, None)
        if not runtime:
            return
        try:
            stop_demo_session(get_demo(str(runtime.get("demo_id") or "")), runtime)
        except Exception as exc:
            try:
                self._record_session_log(self.get(session_id), "cleanup", "stderr", str(exc))
            except KeyError:
                self.event_bus.publish("session.log", {"session_id": session_id, "time": _now(), "phase": "cleanup", "stream": "stderr", "message": str(exc)})

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

    def check_board_safety(self) -> dict[str, Any]:
        thermal_status = self.thermal_guard.status(refresh=True)
        failed_session_id = None
        failed_session = None
        wipe_result = None
        wiped = False
        became_unavailable = not thermal_status.available and not self._board_unavailable
        self._board_unavailable = not thermal_status.available
        promoted = False
        now = _now()
        with self._connect() as conn:
            active = conn.execute("SELECT id FROM sessions WHERE state IN ('starting', 'active', 'releasing') ORDER BY created_at ASC LIMIT 1").fetchone()
            if not thermal_status.available and active is not None:
                failed_session_id = active["id"]
        if became_unavailable:
            wipe_result = self.board_wiper.wipe()
            wiped = True
            self.event_bus.publish("safety.wipe", {"thermal": thermal_status.to_dict(), "wipe": wipe_result})
        if failed_session_id is not None:
            reason = thermal_status.reason or "thermal status unavailable"
            failed_session_before_update = self.get(failed_session_id)
            self._record_session_log(failed_session_before_update, "safety", "stderr", f"thermal lockout: {reason}")
            if not wiped:
                wipe_result = self.board_wiper.wipe()
                wiped = True
                self.event_bus.publish("safety.wipe", {"session_id": failed_session_id, "reason": "thermal_lockout", "thermal": thermal_status.to_dict(), "wipe": wipe_result})
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET state = 'failed', released_at = ?, error = ? WHERE id = ? AND state IN ('starting', 'active', 'releasing')",
                    (now, f"thermal lockout: {reason}", failed_session_id),
                )
            failed_session = self.get(failed_session_id)
            self.event_bus.publish("safety.lockout", {"thermal": thermal_status.to_dict(), "session": session_to_dict(failed_session), "wipe": wipe_result})
            self.event_bus.publish("session.finished", {"session": session_to_dict(failed_session)})
            self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
        elif thermal_status.available:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                active = conn.execute("SELECT id FROM sessions WHERE state IN ('starting', 'active', 'releasing') ORDER BY created_at ASC LIMIT 1").fetchone()
                if active is None:
                    promoted = self._promote_next_locked(conn)
            if promoted:
                self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
                self._start_current_starting_session(ignore_errors=True)
        status = self.board_status(thermal_status=thermal_status)
        self._publish_board_status(status)
        return status

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

    def board_status(self, *, thermal_status=None) -> dict[str, Any]:
        thermal = (thermal_status or self.thermal_guard.snapshot()).to_dict()
        stale = thermal_status is None and thermal.get("temperature_c") is None and thermal.get("reason") == "FPGA thermal status has not been checked yet"
        summary = self.queue_summary()
        locked = summary["active_session_id"]
        return {
            "board": {"available": thermal.get("available") is True and locked is None, "mode": "leased" if locked else "idle", "locked_by_session_id": locked},
            "thermal": {**thermal, "stale": stale},
        }

    def status_snapshot(self) -> dict[str, Any]:
        self.check_session_policy()
        state = self.board_status()
        return {"api": {"status": "ok"}, **state, "sessions": {"active_session_id": state["board"]["locked_by_session_id"], "queued": self.queue_summary()["queued"]}}

    def check_session_policy(self) -> None:
        now = datetime.now(UTC)
        with self._connect() as conn:
            active = conn.execute("SELECT * FROM sessions WHERE state = 'active' ORDER BY created_at ASC LIMIT 1").fetchone()
            queued = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE state = 'queued'").fetchone()["n"]
            if active is None or not active["lease_expires_at"] or not active["lease_started_at"]:
                return
            session_id = active["id"]
            expires = datetime.fromisoformat(active["lease_expires_at"])
            starts = datetime.fromisoformat(active["lease_started_at"])
            remaining = int((expires - now).total_seconds())
            max_expiry = starts + timedelta(seconds=DEFAULT_MAX_TOTAL_SECONDS)
            if remaining <= 60 and queued == 0 and expires < max_expiry:
                new_expiry = min(expires + timedelta(seconds=DEFAULT_EXTENSION_SECONDS), max_expiry)
                conn.execute("UPDATE sessions SET lease_expires_at = ? WHERE id = ?", (_iso(new_expiry), session_id))
                session = self.get(session_id)
                self.event_bus.publish("session.updated", {"session": session_to_dict(session), "extension": "automatic"})
                self._expiry_warned.pop(session_id, None)
                return
            if remaining <= 0:
                self._cleanup_runtime(session_id)
                conn.execute("UPDATE sessions SET state = 'expired', released_at = ? WHERE id = ?", (_now(), session_id))
                self.board_wiper.wipe()
                self._promote_next_locked(conn)
                session = self.get(session_id)
                self.event_bus.publish("session.finished", {"session": session_to_dict(session)})
                self.event_bus.publish("queue.changed", {"queue": self.queue_summary()})
                self._start_current_starting_session(ignore_errors=True)
                return
            for threshold in (60, 30, 10):
                if remaining <= threshold and threshold not in self._expiry_warned.setdefault(session_id, set()):
                    self._expiry_warned[session_id].add(threshold)
                    reason = "another_user_waiting" if queued else "maximum_duration_reached"
                    self.event_bus.publish("session.expiring", {"session_id": session_id, "remaining_seconds": remaining, "lease_expires_at": active["lease_expires_at"], "reason": reason})

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

    def _promote_next_locked(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT id FROM sessions WHERE state = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
        if row is None:
            return False
        now_dt = datetime.now(UTC)
        conn.execute(
            "UPDATE sessions SET state = 'starting', lease_started_at = ?, lease_expires_at = ? WHERE id = ?",
            (_iso(now_dt), _iso(now_dt + timedelta(seconds=DEFAULT_LEASE_SECONDS)), row["id"]),
        )
        return True

    def _start_current_starting_session(self, *, ignore_errors: bool = False) -> Session | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM sessions WHERE state = 'starting' ORDER BY created_at ASC LIMIT 1").fetchone()
        if row is None:
            return None
        try:
            return self.start_session(row["id"])
        except SessionStartFailed:
            if not ignore_errors:
                raise
            return self.get(row["id"])

    def _publish_board_status(self, status: dict[str, Any] | None = None, *, force: bool = False) -> None:
        payload = status or self.board_status()
        key = json.dumps(_board_status_event_key(payload), sort_keys=True)
        if force or key != self._last_board_status_event_key:
            self._last_board_status_event_key = key
            self.event_bus.publish("board.status", payload)

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
            owner_token=row["owner_token"],
        )


def session_to_dict(session: Session, *, artifacts: list[dict[str, Any]] | None = None, include_owner_token: bool = False) -> dict[str, Any]:
    lease = None
    if session.lease_started_at and session.lease_expires_at:
        remaining = max(0, int((datetime.fromisoformat(session.lease_expires_at) - datetime.now(UTC)).total_seconds()))
        lease = {"starts_at": session.lease_started_at, "expires_at": session.lease_expires_at, "remaining_seconds": remaining, "duration_seconds": DEFAULT_LEASE_SECONDS}
    data = {
        "id": session.id,
        "project_id": session.project_id,
        "state": session.state,
        "queue_position": session.queue_position,
        "lease": lease,
        "access": {"url": f"/api/sessions/{session.id}/demo/", "token_required": True} if session.state == "active" else None,
        "created_at": session.created_at,
        "released_at": session.released_at,
        "artifacts": artifacts or [],
        "error": session.error,
    }
    if include_owner_token:
        data["owner_token"] = session.owner_token
    return data


def artifact_to_dict(session_id: str, artifact: Artifact) -> dict[str, Any]:
    return {"name": artifact.name, "kind": artifact.kind, "url": f"/api/sessions/{session_id}/artifacts/{artifact.name}", "content_type": artifact.content_type}


def _board_status_event_key(status: dict[str, Any]) -> dict[str, Any]:
    thermal = dict(status.get("thermal") or {})
    thermal.pop("checked_at", None)
    return {"board": status.get("board"), "thermal": thermal}


def _safe_artifact_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name in {".", ".."} or ".." in Path(name).parts:
        raise ValueError("invalid artifact name")
    return name


class SessionLimitExceeded(RuntimeError):
    pass


class SessionStartFailed(RuntimeError):
    def __init__(self, session_id: str, message: str):
        super().__init__(message)
        self.session_id = session_id


def _now() -> str:
    return _iso(datetime.now(UTC))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
