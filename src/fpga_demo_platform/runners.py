from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fpga_demo_platform.demos import Demo

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GPGPU_NBODY_ROOT = PACKAGE_ROOT / "demos" / "gpgpu-nbody"
DEFAULT_UART_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD = 115200


def run_demo(demo: Demo, payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if demo.id == "gpgpu-nbody":
        return run_gpgpu_nbody(demo, payload, artifact_dir)
    raise ValueError(f"unsupported demo {demo.id!r}")


def build_gpgpu_nbody_command(
    *,
    root: Path,
    port: str,
    dataset: str,
    steps_per_frame: int,
    baud: int = DEFAULT_BAUD,
    kernel_calls: int = 1,
) -> list[str]:
    return [
        sys.executable,
        str(root / "programs" / "fpga_run.py"),
        "-p",
        "nbody-3d",
        "--port",
        port,
        "--baud",
        str(baud),
        "--kernel-calls",
        str(kernel_calls),
        "--no-visualize",
        "--steps",
        str(steps_per_frame),
    ]


def run_gpgpu_nbody(
    demo: Demo,
    payload: dict[str, Any],
    artifact_dir: Path,
    *,
    demo_root: Path = DEFAULT_GPGPU_NBODY_ROOT,
    port: str = DEFAULT_UART_PORT,
    baud: int = DEFAULT_BAUD,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dataset = str(payload.get("dataset", "default"))
    steps_per_frame = int(payload.get("steps_per_frame", 1))
    command = build_gpgpu_nbody_command(
        root=demo_root,
        port=port,
        dataset=dataset,
        steps_per_frame=steps_per_frame,
        baud=baud,
        kernel_calls=1,
    )
    completed = subprocess.run(
        command,
        cwd=demo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    (artifact_dir / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    (artifact_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (artifact_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")

    result = {
        "demo": demo.id,
        "adapter": "gpgpu-fpga-run",
        "board": demo.board,
        "input": payload,
        "returncode": completed.returncode,
        "status": "completed" if completed.returncode == 0 else "failed",
    }
    (artifact_dir / "gpgpu-nbody.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"GPGPU nbody run failed with exit code {completed.returncode}")
    return result
