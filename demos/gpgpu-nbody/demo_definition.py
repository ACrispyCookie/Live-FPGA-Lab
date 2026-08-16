from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEMO_DEFINITION = {
    "id": "gpgpu-nbody",
    "name": "GPGPU n-body simulator",
    "description": "Interactive n-body simulation running through the ZYNQ PS/PL GPGPU demo stack.",
    "bitstream": "bitstream/gpgpu_system_hello.bit",
    "ps7_init_tcl": "boot/ps7_init.tcl",
    "elf": "boot/gpgpu_app.elf",
}

DEMO = {
    **DEMO_DEFINITION,
    "kind": "zynq-ps-pl",
    "board": "HelloFPGA ZYNQ7000",
    "summary": DEMO_DEFINITION["description"],
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
    if not Path(DEFAULT_UART_PORT).exists():
        message = f"UART device {DEFAULT_UART_PORT} is not present; refusing to program board"
        emit_log("preflight", "stderr", message)
        raise RuntimeError(message)
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
            stdout_log.close()
            stderr_log.close()
            _emit_recent_lines(runtime_stderr_path := artifact_dir / "runtime-stderr.log", emit_log, phase="start_demo", stream="stderr")
            raise RuntimeError(f"GPGPU interactive demo exited during startup with code {process.returncode}; see {runtime_stderr_path.name}")
        if _http_ready(port):
            emit_log("start_demo", "stdout", "existing GPGPU demo is ready")
            return {"demo_id": demo.id, "process": process, "port": port, "access_url": f"/api/sessions/{session_id}/demo/"}
        time.sleep(0.1)
    process.terminate()
    stdout_log.close()
    stderr_log.close()
    _emit_recent_lines(artifact_dir / "runtime-stderr.log", emit_log, phase="start_demo", stream="stderr")
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


def _emit_recent_lines(path: Path, emit_log, *, phase: str, stream: str, limit: int = 12) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        if line.strip():
            emit_log(phase, stream, line)
