from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass(frozen=True)
class DemoDefinition:
    id: str
    name: str
    root: Path
    description: str | None = None
    bitstream: Path | None = None
    ps7_init_tcl: Path | None = None
    elf: Path | None = None


def load_demos(demo_dir: Path) -> dict[str, DemoDefinition]:
    """Load demo definitions from immediate subfolders of demo_dir."""
    demo_dir = demo_dir.expanduser().resolve()
    if not demo_dir.exists():
        return {}
    if not demo_dir.is_dir():
        raise ValueError(f"demo directory is not a directory: {demo_dir}")

    demos: dict[str, DemoDefinition] = {}
    for definition_path in sorted(demo_dir.glob("*/demo_definition.py")):
        demo = _load_definition(definition_path)
        if demo.id in demos:
            raise ValueError(f"duplicate demo id {demo.id!r} in {definition_path}")
        demos[demo.id] = demo
    return demos


def _load_definition(path: Path) -> DemoDefinition:
    module = _load_module(path)
    raw = getattr(module, "DEMO_DEFINITION", None)
    if raw is None:
        raw = getattr(module, "DEMO", None)
    if raw is None:
        raise ValueError(f"{path} must define DEMO_DEFINITION or DEMO")

    root = path.parent
    if isinstance(raw, DemoDefinition):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(f"{path} demo definition must be a dict or DemoDefinition")

    demo_id = _required_str(raw, "id", path)
    name = _required_str(raw, "name", path)
    description = raw.get("description") or raw.get("summary")
    return DemoDefinition(
        id=demo_id,
        name=name,
        root=root,
        description=str(description) if description is not None else None,
        bitstream=_optional_path(raw, "bitstream", root),
        ps7_init_tcl=_optional_path(raw, "ps7_init_tcl", root),
        elf=_optional_path(raw, "elf", root),
    )


def _load_module(path: Path) -> ModuleType:
    module_name = f"web_api_demo_definition_{path.parent.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load demo definition: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _required_str(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} field {key!r} must be a non-empty string")
    return value


def _optional_path(raw: dict[str, Any], key: str, root: Path) -> Path | None:
    value = raw.get(key)
    if value is None or value == "":
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path
