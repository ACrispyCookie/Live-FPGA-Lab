from __future__ import annotations

import importlib.util
import os
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


def get_demo(demo_id: str) -> Demo:
    demos = _demo_registry()
    try:
        return demos[demo_id]
    except KeyError as exc:
        raise KeyError(f"unknown demo '{demo_id}'") from exc


def list_demos() -> list[Demo]:
    return list(_demo_registry().values())


def load_demo_module(demo: Demo) -> ModuleType:
    return _load_module(demo.definition_path, module_name=f"fpga_demo_definition_{demo.id.replace('-', '_')}")


def _demo_registry(root: Path = DEFAULT_DEMOS_ROOT) -> dict[str, Demo]:
    demos: dict[str, Demo] = {}
    if not root.exists():
        return demos
    for definition_path in sorted(root.glob(f"*/{DEFINITION_FILE}")):
        module = _load_module(definition_path, module_name=f"fpga_demo_definition_{definition_path.parent.name}")
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


def _load_module(path: Path, *, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load demo definition at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
