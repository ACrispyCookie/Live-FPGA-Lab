from __future__ import annotations

import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BITSTREAM = Path(os.environ.get("DVD_LOGO_BITSTREAM", ROOT / "bitstream" / "dvd_logo.bit"))
VIDEO_DEVICE = os.environ.get("DEMO_VIDEO_DEVICE", "/dev/fpga-video")
VIDEO_SIZE = os.environ.get("DEMO_VIDEO_SIZE", "640x480")
VIDEO_FPS = int(os.environ.get("DEMO_VIDEO_FPS", "60"))
VIDEO_INPUT_FORMAT = os.environ.get("DEMO_VIDEO_INPUT_FORMAT", "mjpeg")
HTTP_HOST = os.environ.get("DEMO_HTTP_HOST", "127.0.0.1")
HTTP_PORT = os.environ.get("DEMO_HTTP_PORT")


DEMO_DEFINITION = {
    "id": "dvd-logo-video",
    "name": "DVD Logo HDMI",
    "description": "Live HDMI output captured directly from the FPGA.",
    # Drop the future build at bitstream/dvd_logo.bit (or set
    # DVD_LOGO_BITSTREAM) and restart web-api to enable programming.
    "bitstream": str(BITSTREAM) if BITSTREAM.is_file() else None,
}


def start_session(*, demo, session_id: str) -> dict[str, Any]:
    _validate_capture_device(VIDEO_DEVICE)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for the HDMI capture demo")

    port = int(HTTP_PORT) if HTTP_PORT else _free_port()
    command = [
        sys.executable,
        str(demo.root / "video_stream.py"),
        "--device", VIDEO_DEVICE,
        "--host", HTTP_HOST,
        "--port", str(port),
        "--size", VIDEO_SIZE,
        "--fps", str(VIDEO_FPS),
        "--input-format", VIDEO_INPUT_FORMAT,
    ]
    process = subprocess.Popen(command, cwd=demo.root, start_new_session=True)
    deadline = time.monotonic() + 15

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Video demo exited with code {process.returncode}")
        if _port_open(port):
            return {
                "process": process,
                "backend": f"http://{HTTP_HOST}:{port}",
            }
        time.sleep(0.1)

    _stop_process(process)
    raise RuntimeError("Video demo HTTP server did not start")


def stop_session(runtime: dict[str, Any]) -> None:
    process = runtime.get("process")
    if isinstance(process, subprocess.Popen):
        _stop_process(process)


def _validate_capture_device(device: str) -> None:
    path = Path(device)
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise RuntimeError(f"Video capture device not found: {device}") from exc
    if not stat.S_ISCHR(mode):
        raise RuntimeError(f"Video capture path is not a character device: {device}")


def _stop_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HTTP_HOST, 0))
        return int(sock.getsockname()[1])


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False
