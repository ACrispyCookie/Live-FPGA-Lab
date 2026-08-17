from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEMO_DEFINITION = {
    "id": "gpgpu-nbody",
    "name": "GPGPU n-body simulator",
    "description": "Interactive n-body simulation running on the FPGA.",
    "bitstream": "bitstream/gpgpu_system_hello.bit",
    "ps7_init_tcl": "boot/ps7_init.tcl",
    "elf": "boot/gpgpu_app.elf",
}


UART_PORT = "/dev/ttyUSB1"
BAUD = 115200
BIND = "0.0.0.0"
PORT = 9130


def start_session(*, demo, session_id: str) -> dict[str, Any]:
    port = PORT

    command = [
        sys.executable,
        str(demo.root / "demo" / "interactive_3d.py"),
        "--port", UART_PORT,
        "--baud", str(BAUD),
        "--dataset", "rings",
        "--imem", str(
            demo.root
            / "programs"
            / "nbody-3d"
            / "nbody-3d_instructions.mem"
        ),
        "--http-host", BIND,
        "--http-port", str(port),
        "--no-browser",
    ]

    process = subprocess.Popen(
        command,
        cwd=demo.root,
    )

    deadline = time.monotonic() + 10

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Demo exited with code {process.returncode}"
            )

        if _port_open(port):
            return {
                "process": process,
                "backend": f"http://{BIND}:{port}",
            }

        time.sleep(0.1)

    process.terminate()
    raise RuntimeError("Demo HTTP server did not start")


def stop_session(runtime: dict[str, Any]) -> None:
    process = runtime.get("process")

    if not isinstance(process, subprocess.Popen):
        return

    process.terminate()

    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()

def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(
            (BIND, port),
            timeout=0.2,
        ):
            return True
    except OSError:
        return False
