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
DEFAULT_XSDB = Path("/home/njason/Xilinx/2025.2/Vitis/bin/xsdb")


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


def build_gpgpu_program_script(*, root: Path) -> str:
    bitstream = root / "bitstream" / "gpgpu_system_hello.bit"
    ps7_init = root / "boot" / "ps7_init.tcl"
    app_elf = root / "boot" / "gpgpu_app.elf"
    return f"""
connect
puts {{fpga-demo: connected}}
targets -set -filter {{name =~ "xc7z020"}}
fpga -file {bitstream}
puts {{fpga-demo: programmed PL}}
targets -set -filter {{name =~ "ARM Cortex-A9 MPCore #0"}}
rst -processor
source {ps7_init}
ps7_init
ps7_post_config
dow {app_elf}
con
puts {{fpga-demo: started PS application}}
after 1000
exit
""".strip()


def program_gpgpu_board(*, root: Path, artifact_dir: Path, xsdb: Path = DEFAULT_XSDB) -> None:
    script = build_gpgpu_program_script(root=root)
    script_path = artifact_dir / "program-gpgpu.tcl"
    script_path.write_text(script + "\n", encoding="utf-8")
    completed = subprocess.run(
        [str(xsdb), str(script_path.resolve())],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    (artifact_dir / "program-stdout.log").write_text(completed.stdout, encoding="utf-8")
    (artifact_dir / "program-stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"GPGPU board programming failed with exit code {completed.returncode}")


def run_gpgpu_nbody(
    demo: Demo,
    payload: dict[str, Any],
    artifact_dir: Path,
    *,
    demo_root: Path = DEFAULT_GPGPU_NBODY_ROOT,
    port: str = DEFAULT_UART_PORT,
    baud: int = DEFAULT_BAUD,
    program_board: bool = True,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dataset = str(payload.get("dataset", "default"))
    steps_per_frame = int(payload.get("steps_per_frame", 1))
    if program_board:
        program_gpgpu_board(root=demo_root, artifact_dir=artifact_dir)
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
        "programmed": program_board,
        "returncode": completed.returncode,
        "status": "completed" if completed.returncode == 0 else "failed",
    }
    (artifact_dir / "gpgpu-nbody.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"GPGPU nbody run failed with exit code {completed.returncode}")
    return result
