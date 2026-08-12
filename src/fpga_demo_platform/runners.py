from __future__ import annotations

from pathlib import Path
from typing import Any

from fpga_demo_platform.demos import Demo, load_demo_module


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
