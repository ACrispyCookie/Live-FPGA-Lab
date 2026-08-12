from __future__ import annotations

from pathlib import Path
from typing import Any

from fpga_demo_platform.demos import Demo


def run_demo(demo: Demo, payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if demo.id == "gpgpu-nbody":
        return run_gpgpu_nbody(demo, payload, artifact_dir)
    raise ValueError(f"unsupported demo {demo.id!r}")


def run_gpgpu_nbody(demo: Demo, payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    result = {
        "demo": demo.id,
        "adapter": "gpgpu-interactive",
        "board": demo.board,
        "input": payload,
        "status": "integration-ready",
    }
    (artifact_dir / "gpgpu-nbody.json").write_text(
        __import__("json").dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result
