from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from fpga_demo_platform.demos import list_demos
from fpga_demo_platform.queue import JobQueue, job_to_dict
from fpga_demo_platform.thermal import HardwareUnavailable
from fpga_demo_platform.web import INDEX_HTML


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


def demo_to_dict(demo) -> dict[str, Any]:
    return {
        "id": demo.id,
        "name": demo.name,
        "kind": demo.kind,
        "board": demo.board,
        "summary": demo.summary,
        "available": demo.available,
        "placeholder": demo.placeholder,
    }


def create_app(*, queue: JobQueue) -> FastAPI:
    app = FastAPI(title="FPGA Demo Platform", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return {
            "thermal": queue.thermal_status(),
            "jobs": [job_to_dict(job) for job in queue.list_recent(limit=10)],
        }

    @app.get("/api/demos")
    def api_list_demos() -> list[dict[str, Any]]:
        return [demo_to_dict(demo) for demo in list_demos()]

    @app.post("/api/demos/{demo_id}/run", status_code=status.HTTP_201_CREATED)
    def submit_run(demo_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
        try:
            job = queue.submit(demo_id, body.input, requester=request.client.host if request.client else None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HardwareUnavailable as exc:
            raise HTTPException(status_code=503, detail={"message": str(exc), "thermal": exc.status.to_dict()}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return job_to_dict(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return job_to_dict(queue.get(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/worker/run-next")
    def worker_run_next() -> dict[str, Any]:
        try:
            job = queue.run_next()
        except HardwareUnavailable as exc:
            raise HTTPException(status_code=503, detail={"message": str(exc), "thermal": exc.status.to_dict()}) from exc
        if job is None:
            return {"status": "idle"}
        return job_to_dict(job)

    return app


def app_from_paths(db_path: str | Path, artifacts_dir: str | Path) -> FastAPI:
    queue = JobQueue(db_path, artifacts_dir)
    return create_app(queue=queue)
