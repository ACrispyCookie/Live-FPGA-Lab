from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEMO_ROOT = Path(__file__).resolve().parents[2] / "demos"


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    source: str
    source_ref: str
    status: str
    runnable: bool
    demo_id: str | None = None


def list_projects(demos_root: Path = DEMO_ROOT) -> list[Project]:
    projects: list[Project] = []
    for path in sorted(demos_root.glob("*/projects.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            projects.append(_project_from_dict(item, source_file=path))
    return projects


def get_project(project_id: str, demos_root: Path = DEMO_ROOT) -> Project:
    for project in list_projects(demos_root):
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


def _project_from_dict(item: dict[str, Any], *, source_file: Path) -> Project:
    required = ["id", "name", "source", "source_ref", "status", "runnable"]
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"{source_file} missing required project field(s): {', '.join(missing)}")
    runnable = bool(item["runnable"])
    demo_id = item.get("demo_id")
    if runnable and not isinstance(demo_id, str):
        raise ValueError(f"{source_file} runnable project {item['id']} must declare demo_id")
    return Project(
        id=str(item["id"]),
        name=str(item["name"]),
        source=str(item["source"]),
        source_ref=str(item["source_ref"]),
        status=str(item["status"]),
        runnable=runnable,
        demo_id=str(demo_id) if demo_id is not None else None,
    )
