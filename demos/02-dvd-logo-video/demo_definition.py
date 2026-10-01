from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import threading
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BITSTREAM = Path(os.environ.get("DVD_LOGO_BITSTREAM", ROOT / "bitstream" / "dvd_logo.bit"))
VIDEO_DEVICE = os.environ.get("DEMO_VIDEO_DEVICE", "/dev/fpga-video")
HTTP_HOST = os.environ.get("DEMO_HTTP_HOST", "127.0.0.1")
HTTP_PORT = os.environ.get("DEMO_HTTP_PORT")

DEMO_DEFINITION = {
    "id": "dvd-logo-video",
    "name": "DVD Logo HDMI",
    "description": "Live HDMI output captured directly from the FPGA.",
    "bitstream": str(BITSTREAM) if BITSTREAM.is_file() else None,
}


def start_session(*, demo, session_id: str) -> dict[str, Any]:
    from web_api.video import get_video_service

    _validate_capture_device(VIDEO_DEVICE)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for the HDMI capture demo")

    # Demo modules are loaded by path, so load the sibling without modifying
    # sys.path. Keeping this HTTP view in-process lets /video share the producer.
    spec = importlib.util.spec_from_file_location("dvd_logo_http", demo.root / "video_stream.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load HDMI capture HTTP server")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = module.CaptureServer(
        (HTTP_HOST, int(HTTP_PORT) if HTTP_PORT else 0),
        module.Handler,
        service=get_video_service(),
    )
    try:
        server.start_capture()
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name=f"dvd-video-{session_id}",
            daemon=True,
        )
        thread.start()
    except BaseException:
        server.stop_capture()
        server.server_close()
        raise
    backend_host = "127.0.0.1" if HTTP_HOST == "0.0.0.0" else HTTP_HOST
    return {
        "server": server,
        "thread": thread,
        "backend": f"http://{backend_host}:{server.server_address[1]}",
    }


def stop_session(runtime: dict[str, Any]) -> None:
    server = runtime["server"]
    try:
        server.stop_capture()
        server.shutdown()
    finally:
        server.server_close()
        runtime["thread"].join(timeout=2)


def _validate_capture_device(device: str) -> None:
    path = Path(device)
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise RuntimeError(f"Video capture device not found: {device}") from exc
    if not stat.S_ISCHR(mode):
        raise RuntimeError(f"Video capture path is not a character device: {device}")
