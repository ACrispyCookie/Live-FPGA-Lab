from __future__ import annotations

import csv
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEMO = {
    "id": "gpgpu-nbody",
    "name": "GPGPU n-body simulator",
    "kind": "zynq-ps-pl",
    "board": "HelloFPGA ZYNQ7000",
    "summary": "Interactive n-body simulation running through the ZYNQ PS/PL GPGPU demo stack.",
    "available": True,
    "placeholder": False,
}

PROJECTS = [
    {"id": "ece338-gpgpu-nbody-3d", "name": "GPGPU n-body 3D", "source": "ECE338", "source_ref": "programs/nbody-3d", "status": "runnable", "runnable": True, "demo_id": "gpgpu-nbody"},
    {"id": "ece338-gpgpu-nbody-2d", "name": "GPGPU n-body 2D", "source": "ECE338", "source_ref": "programs/nbody", "status": "source-only", "runnable": False},
    {"id": "ece338-gpgpu-mandelbrot", "name": "GPGPU Mandelbrot", "source": "ECE338", "source_ref": "programs/mandelbrot", "status": "source-only", "runnable": False},
    {"id": "ece338-gpgpu-differences", "name": "GPGPU Differences", "source": "ECE338", "source_ref": "programs/differences", "status": "source-only", "runnable": False},
    {"id": "ece338-gpgpu-sobel", "name": "GPGPU Sobel", "source": "ECE338", "source_ref": "programs/sobel", "status": "source-only", "runnable": False},
    {"id": "ece338-gpgpu-simple", "name": "GPGPU Simple", "source": "ECE338", "source_ref": "programs/simple", "status": "source-only", "runnable": False},
    {"id": "ece338-gpgpu-stacktest", "name": "GPGPU Stack Test", "source": "ECE338", "source_ref": "programs/stacktest", "status": "source-only", "runnable": False},
]

DEFAULT_UART_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD = 115200
DEFAULT_XSDB = Path("/home/njason/Xilinx/2025.2/Vitis/bin/xsdb")


def validate_input(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(payload or {})
    allowed = {"dataset", "steps_per_frame", "kernel_calls", "fps"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unsupported input field(s): {', '.join(unknown)}")

    dataset = payload.get("dataset", "default")
    if not isinstance(dataset, str) or not dataset:
        raise ValueError("dataset must be a non-empty string")

    steps_per_frame = payload.get("steps_per_frame", 1)
    if not isinstance(steps_per_frame, int) or not 1 <= steps_per_frame <= 10240:
        raise ValueError("steps_per_frame must be an integer from 1 to 10240")

    kernel_calls = payload.get("kernel_calls", 1)
    if not isinstance(kernel_calls, int) or not 1 <= kernel_calls <= 4:
        raise ValueError("kernel_calls must be an integer from 1 to 4")

    fps = payload.get("fps", 12.0)
    if not isinstance(fps, int | float) or not 1.0 <= float(fps) <= 60.0:
        raise ValueError("fps must be a number from 1 to 60")

    return {
        "dataset": dataset,
        "steps_per_frame": steps_per_frame,
        "kernel_calls": kernel_calls,
        "fps": float(fps),
    }


def run(*, demo: Any, payload: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    return run_gpgpu_nbody(demo=demo, payload=payload, artifact_dir=artifact_dir, demo_root=demo.root)


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


def stream_gpgpu_programming(*, root: Path, artifact_dir: Path, emit_log, xsdb: Path = DEFAULT_XSDB) -> None:
    script = build_gpgpu_program_script(root=root)
    script_path = artifact_dir / "program-gpgpu.tcl"
    script_path.write_text(script + "\n", encoding="utf-8")
    stdout_path = artifact_dir / "program-stdout.log"
    stderr_path = artifact_dir / "program-stderr.log"
    process = subprocess.Popen(
        [str(xsdb), str(script_path.resolve())],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    with stdout_path.open("w", encoding="utf-8") as stdout_log, stderr_path.open("w", encoding="utf-8") as stderr_log:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\n")
            stdout_log.write(raw)
            stdout_log.flush()
            emit_log("program_board", "stdout", line)
        returncode = process.wait(timeout=5)
        if returncode != 0:
            message = f"GPGPU board programming failed with exit code {returncode}"
            stderr_log.write(message + "\n")
            emit_log("program_board", "stderr", message)
            raise RuntimeError(message)


def start_session(*, demo: Any, session_id: str, artifact_dir: Path, emit_log) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    emit_log("program_board", "stdout", "starting PL bitstream and PS app load")
    stream_gpgpu_programming(root=demo.root, artifact_dir=artifact_dir, emit_log=emit_log)
    port = _free_local_port()
    command = [
        sys.executable,
        str(demo.root / "demo" / "interactive_3d.py"),
        "--port",
        DEFAULT_UART_PORT,
        "--baud",
        str(DEFAULT_BAUD),
        "--imem",
        str(demo.root / "programs" / "nbody-3d" / "nbody-3d_instructions.mem"),
        "--skip-load-imem",
        "--http-host",
        "127.0.0.1",
        "--http-port",
        str(port),
        "--no-browser",
    ]
    (artifact_dir / "demo-command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    stdout_log = (artifact_dir / "runtime-stdout.log").open("w", encoding="utf-8")
    stderr_log = (artifact_dir / "runtime-stderr.log").open("w", encoding="utf-8")
    emit_log("start_demo", "stdout", f"starting existing GPGPU demo on 127.0.0.1:{port}")
    process = subprocess.Popen(command, cwd=demo.root, text=True, stdout=stdout_log, stderr=stderr_log)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"GPGPU interactive demo exited during startup with code {process.returncode}")
        if _http_ready(port):
            emit_log("start_demo", "stdout", "existing GPGPU demo is ready")
            return {"demo_id": demo.id, "process": process, "port": port, "access_url": f"/api/sessions/{session_id}/demo/"}
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError("GPGPU interactive demo did not become ready")


def stop_session(runtime: dict[str, Any]) -> None:
    process = runtime.get("process")
    if isinstance(process, subprocess.Popen):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def parse_nbody_csv(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            positions = []
            for body in range(32):
                positions.append([
                    int(row.get(f"x{body}", "0") or 0),
                    int(row.get(f"y{body}", "0") or 0),
                    int(row.get(f"z{body}", "0") or 0),
                ])
            frames.append({"step": int(row.get("step", "0") or 0), "positions": positions})
    return frames


def run_gpgpu_nbody(
    *,
    demo: Any,
    payload: dict[str, Any],
    artifact_dir: Path,
    demo_root: Path,
    port: str = DEFAULT_UART_PORT,
    baud: int = DEFAULT_BAUD,
    program_board: bool = True,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dataset = str(payload.get("dataset", "default"))
    steps_per_frame = int(payload.get("steps_per_frame", 1))
    kernel_calls = int(payload.get("kernel_calls", 1))
    if program_board:
        program_gpgpu_board(root=demo_root, artifact_dir=artifact_dir)
    command = build_gpgpu_nbody_command(
        root=demo_root,
        port=port,
        dataset=dataset,
        steps_per_frame=steps_per_frame,
        baud=baud,
        kernel_calls=kernel_calls,
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

    csv_path = demo_root / "programs" / "nbody-3d" / "data.csv"
    frames: list[dict[str, Any]] = []
    if csv_path.exists():
        artifact_csv = artifact_dir / "data.csv"
        shutil.copy2(csv_path, artifact_csv)
        frames = parse_nbody_csv(artifact_csv)
        (artifact_dir / "frames.json").write_text(json.dumps({"frames": frames}, indent=2), encoding="utf-8")

    result = {
        "demo": demo.id,
        "adapter": "gpgpu-fpga-run",
        "board": demo.board,
        "input": payload,
        "frames": frames,
        "frames_count": len(frames),
        "artifact_files": ["command.json", "stdout.log", "stderr.log", "gpgpu-nbody.json", "summary.json"]
        + (["data.csv", "frames.json"] if frames else []),
        "programmed": program_board,
        "returncode": completed.returncode,
        "status": "completed" if completed.returncode == 0 else "failed",
    }
    (artifact_dir / "gpgpu-nbody.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"GPGPU nbody run failed with exit code {completed.returncode}")
    return result
