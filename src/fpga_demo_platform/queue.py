from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from fpga_demo_platform.demos import get_demo
from fpga_demo_platform.runners import run_demo


JobStatus = Literal["queued", "running", "succeeded", "failed"]
Runner = Callable[[str, dict[str, Any], Path], dict[str, Any]]


@dataclass(frozen=True)
class Job:
    id: str
    demo_id: str
    status: JobStatus
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    artifact_dir: str | None
    requester: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class JobQueue:
    def __init__(
        self,
        db_path: str | Path,
        artifacts_dir: str | Path,
        *,
        runner: Runner | None = None,
    ):
        self.db_path = Path(db_path)
        self.artifacts_dir = Path(artifacts_dir)
        self.runner = runner or _default_runner
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    demo_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    artifact_dir TEXT,
                    requester TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )

    def submit(self, demo_id: str, payload: dict[str, Any] | None, requester: str | None = None) -> Job:
        demo = get_demo(demo_id)
        clean_payload = demo.validate_input(payload)
        job_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, demo_id, status, input_json, requester, created_at)
                VALUES (?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, demo_id, json.dumps(clean_payload, sort_keys=True), requester, now),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> Job:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown job '{job_id}'")
        return _job_from_row(row)

    def claim_next(self) -> Job | None:
        with self._connect() as conn:
            running = conn.execute("SELECT id FROM jobs WHERE status = 'running' LIMIT 1").fetchone()
            if running is not None:
                return None
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            artifact_dir = self.artifacts_dir / row["id"]
            artifact_dir.mkdir(parents=True, exist_ok=True)
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ?, artifact_dir = ? WHERE id = ?",
                (_now(), str(artifact_dir), row["id"]),
            )
        return self.get(row["id"])

    def finish(
        self,
        job_id: str,
        *,
        status: Literal["succeeded", "failed"],
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Job:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, result_json = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(result or {}, sort_keys=True), error, _now(), job_id),
            )
        job = self.get(job_id)
        if job.artifact_dir:
            summary_path = Path(job.artifact_dir) / "summary.json"
            summary_path.write_text(json.dumps(job_to_dict(job), indent=2, sort_keys=True), encoding="utf-8")
        return job

    def run_next(self) -> Job | None:
        job = self.claim_next()
        if job is None:
            return None
        try:
            result = self.runner(job.demo_id, job.input, Path(job.artifact_dir or self.artifacts_dir / job.id))
        except Exception as exc:  # noqa: BLE001 - job failures must be captured, not crash worker
            return self.finish(job.id, status="failed", error=str(exc), result={})
        return self.finish(job.id, status="succeeded", result=result)


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "demo_id": job.demo_id,
        "status": job.status,
        "input": job.input,
        "result": job.result,
        "error": job.error,
        "artifact_dir": job.artifact_dir,
        "requester": job.requester,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _default_runner(demo_id: str, payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    return run_demo(get_demo(demo_id), payload, artifact_dir)


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        demo_id=row["demo_id"],
        status=row["status"],
        input=json.loads(row["input_json"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=row["error"],
        artifact_dir=row["artifact_dir"],
        requester=row["requester"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
