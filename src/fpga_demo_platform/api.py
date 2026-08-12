from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from fpga_demo_platform.demos import list_demos
from fpga_demo_platform.queue import JobQueue, job_to_dict


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


def create_app(*, queue: JobQueue) -> FastAPI:
    app = FastAPI(title="FPGA Demo Platform", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/demos")
    def api_list_demos() -> list[dict[str, Any]]:
        return [
            {
                "id": demo.id,
                "name": demo.name,
                "kind": demo.kind,
                "board": demo.board,
                "summary": demo.summary,
            }
            for demo in list_demos()
        ]

    @app.post("/api/demos/{demo_id}/run", status_code=status.HTTP_201_CREATED)
    def submit_run(demo_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
        try:
            job = queue.submit(demo_id, body.input, requester=request.client.host if request.client else None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        job = queue.run_next()
        if job is None:
            return {"status": "idle"}
        return job_to_dict(job)

    return app


def app_from_paths(db_path: str | Path, artifacts_dir: str | Path) -> FastAPI:
    queue = JobQueue(db_path, artifacts_dir)
    return create_app(queue=queue)
