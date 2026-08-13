from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    source: str
    source_ref: str
    status: str
    runnable: bool
    demo_id: str | None = None


PROJECTS = [
    Project("ece338-gpgpu-nbody-3d", "GPGPU n-body 3D", "ECE338", "programs/nbody-3d", "runnable", True, "gpgpu-nbody"),
    Project("ece338-gpgpu-nbody-2d", "GPGPU n-body 2D", "ECE338", "programs/nbody", "source-only", False, None),
    Project("ece338-gpgpu-mandelbrot", "GPGPU Mandelbrot", "ECE338", "programs/mandelbrot", "source-only", False, None),
    Project("ece338-gpgpu-differences", "GPGPU Differences", "ECE338", "programs/differences", "source-only", False, None),
    Project("ece338-gpgpu-sobel", "GPGPU Sobel", "ECE338", "programs/sobel", "source-only", False, None),
    Project("ece338-gpgpu-simple", "GPGPU Simple", "ECE338", "programs/simple", "source-only", False, None),
    Project("ece338-gpgpu-stacktest", "GPGPU Stack Test", "ECE338", "programs/stacktest", "source-only", False, None),
]


def list_projects() -> list[Project]:
    return PROJECTS.copy()


def get_project(project_id: str) -> Project:
    for project in PROJECTS:
        if project.id == project_id:
            return project
    raise KeyError(f"unknown project '{project_id}'")


def project_to_dict(project: Project) -> dict[str, Any]:
    lease = None
    if project.runnable:
        lease = {"duration_seconds": 180, "idle_timeout_seconds": 45, "extension_seconds": 60, "extension_allowed_when_queue_empty": True}
    return {
        "id": project.id,
        "name": project.name,
        "source": project.source,
        "source_ref": project.source_ref,
        "status": project.status,
        "runnable": project.runnable,
        "lease": lease,
    }
