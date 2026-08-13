from __future__ import annotations

import importlib.util
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Literal

DemoKind = Literal["zynq-ps-pl"]
Validator = Callable[[dict[str, Any] | None], dict[str, Any]]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEMOS_ROOT = Path(os.environ.get("FPGA_DEMO_ROOT", PROJECT_ROOT / "demos"))
DEFINITION_FILE = "demo_definition.py"


@dataclass(frozen=True)
class Demo:
    id: str
    name: str
    kind: DemoKind
    board: str
    summary: str
    root: Path
    definition_path: Path
    validate_input_fn: Validator
    available: bool = True
    placeholder: bool = False

    def validate_input(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self.validate_input_fn(payload)


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    source: str
    source_ref: str
    status: str
    runnable: bool
    demo_id: str | None = None


def get_demo(demo_id: str) -> Demo:
    demos = _demo_registry()
    try:
        return demos[demo_id]
    except KeyError as exc:
        raise KeyError(f"unknown demo '{demo_id}'") from exc


def list_demos() -> list[Demo]:
    return list(_demo_registry().values())


def list_projects() -> list[Project]:
    projects: list[Project] = []
    for definition_path, module in _definition_modules():
        raw_projects = getattr(module, "PROJECTS", [])
        if not isinstance(raw_projects, list):
            raise ValueError(f"{definition_path} PROJECTS must be a list")
        projects.extend(_project_from_dict(item, source_file=definition_path) for item in raw_projects)
    return projects


def get_project(project_id: str) -> Project:
    for project in list_projects():
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


def run_demo(demo: Demo, payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    module = load_demo_module(demo)
    runner = getattr(module, "run", None)
    if not callable(runner):
        raise ValueError(f"demo {demo.id!r} does not define run(demo, payload, artifact_dir)")
    result = runner(demo=demo, payload=payload, artifact_dir=artifact_dir)
    if not isinstance(result, dict):
        raise TypeError(f"demo {demo.id!r} runner returned {type(result).__name__}, expected dict")
    return result


def start_demo_session(demo: Demo, *, session_id: str, artifact_dir: Path, emit_log: Callable[[str, str, str], None]) -> dict[str, Any]:
    module = load_demo_module(demo)
    starter = getattr(module, "start_session", None)
    if not callable(starter):
        raise ValueError(f"demo {demo.id!r} does not define start_session(demo, session_id, artifact_dir, emit_log)")
    result = starter(demo=demo, session_id=session_id, artifact_dir=artifact_dir, emit_log=emit_log)
    if not isinstance(result, dict):
        raise TypeError(f"demo {demo.id!r} start_session returned {type(result).__name__}, expected dict")
    return result


def stop_demo_session(demo: Demo, runtime: dict[str, Any]) -> None:
    module = load_demo_module(demo)
    stopper = getattr(module, "stop_session", None)
    if callable(stopper):
        stopper(runtime)
        return
    process = runtime.get("process")
    if isinstance(process, subprocess.Popen):
        process.terminate()


def load_demo_module(demo: Demo) -> ModuleType:
    return _load_module(demo.definition_path, module_name=f"fpga_demo_definition_{demo.id.replace('-', '_')}")


def _demo_registry(root: Path = DEFAULT_DEMOS_ROOT) -> dict[str, Demo]:
    demos: dict[str, Demo] = {}
    for definition_path, module in _definition_modules(root):
        metadata = getattr(module, "DEMO", None)
        validate_input = getattr(module, "validate_input", None)
        if not isinstance(metadata, dict):
            raise ValueError(f"{definition_path} must define DEMO metadata as a dict")
        if not callable(validate_input):
            raise ValueError(f"{definition_path} must define validate_input(payload)")
        demo = Demo(
            id=_require_str(metadata, "id", definition_path),
            name=_require_str(metadata, "name", definition_path),
            kind=_require_kind(metadata, definition_path),
            board=_require_str(metadata, "board", definition_path),
            summary=_require_str(metadata, "summary", definition_path),
            root=definition_path.parent,
            definition_path=definition_path,
            validate_input_fn=validate_input,
            available=bool(metadata.get("available", True)),
            placeholder=bool(metadata.get("placeholder", False)),
        )
        if demo.id in demos:
            raise ValueError(f"duplicate demo id '{demo.id}' from {definition_path}")
        demos[demo.id] = demo
    return demos


def _definition_modules(root: Path = DEFAULT_DEMOS_ROOT) -> list[tuple[Path, ModuleType]]:
    if not root.exists():
        return []
    return [
        (path, _load_module(path, module_name=f"fpga_demo_definition_{path.parent.name}"))
        for path in sorted(root.glob(f"*/{DEFINITION_FILE}"))
    ]


def _load_module(path: Path, *, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load demo definition at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project_from_dict(item: dict[str, Any], *, source_file: Path) -> Project:
    required = ["id", "name", "source", "source_ref", "status", "runnable"]
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"{source_file} PROJECTS item missing field(s): {', '.join(missing)}")
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


def _require_str(metadata: dict[str, Any], key: str, path: Path) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} DEMO['{key}'] must be a non-empty string")
    return value


def _require_kind(metadata: dict[str, Any], path: Path) -> DemoKind:
    value = _require_str(metadata, "kind", path)
    if value != "zynq-ps-pl":
        raise ValueError(f"{path} DEMO['kind'] has unsupported value {value!r}")
    return value
