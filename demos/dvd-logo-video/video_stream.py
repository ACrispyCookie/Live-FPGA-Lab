from __future__ import annotations

import argparse
import json
import logging
import shutil
import signal
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast


LOG = logging.getLogger("dvd-logo-video")
BOUNDARY = "ffmpeg"


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DVD Logo HDMI output</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; background: #05070a; color: #e6edf3; }
    body { display: grid; place-items: center; overflow: hidden; }
    main { position: relative; width: 100%; height: 100%; display: grid; place-items: center; }
    img { display: block; width: 100%; height: 100%; object-fit: contain; image-rendering: auto; }
    .badge { position: absolute; top: 14px; left: 14px; display: flex; align-items: center; gap: 8px;
      padding: 7px 10px; border: 1px solid #30363d; border-radius: 999px;
      background: rgb(13 17 23 / 82%); box-shadow: 0 8px 30px rgb(0 0 0 / 35%); font-size: 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #3fb950; box-shadow: 0 0 10px #3fb950; }
  </style>
</head>
<body>
  <main>
    <img src="stream.mjpg" alt="Live FPGA HDMI output" />
    <div class="badge"><span class="dot"></span>Live FPGA HDMI capture</div>
  </main>
</body>
</html>
"""


class CaptureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, *, ffmpeg_command: list[str]):
        super().__init__(address, handler)
        self.ffmpeg_command = ffmpeg_command
        self._frame_condition = threading.Condition()
        self._latest_frame: bytes | None = None
        self._frame_sequence = 0
        self._capture_process: subprocess.Popen[bytes] | None = None
        self._capture_thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start_capture(self) -> None:
        if self._capture_thread is not None:
            return
        self._capture_thread = threading.Thread(target=self._capture_loop, name="hdmi-capture", daemon=True)
        self._capture_thread.start()

    def wait_for_frame(self, after_sequence: int, timeout: float = 5) -> tuple[int, bytes | None]:
        with self._frame_condition:
            self._frame_condition.wait_for(
                lambda: self._frame_sequence > after_sequence or self._stopping.is_set(),
                timeout=timeout,
            )
            return self._frame_sequence, self._latest_frame

    def stop_capture(self) -> None:
        self._stopping.set()
        process = self._capture_process
        if process is not None:
            _stop_process(process)
        with self._frame_condition:
            self._frame_condition.notify_all()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=4)

    def _capture_loop(self) -> None:
        while not self._stopping.is_set():
            process = subprocess.Popen(
                self.ffmpeg_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._capture_process = process
            try:
                self._read_frames(process)
            finally:
                _stop_process(process)
                self._capture_process = None
            if not self._stopping.wait(1):
                LOG.warning("Capture process exited; retrying video device")

    def _read_frames(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stdout is not None
        buffer = bytearray()
        while not self._stopping.is_set():
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                return
            buffer.extend(chunk)
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    buffer[:] = b"\xff" if buffer.endswith(b"\xff") else b""
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                with self._frame_condition:
                    self._latest_frame = frame
                    self._frame_sequence += 1
                    self._frame_condition.notify_all()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"", "/", "/index.html"}:
            self._send_bytes("text/html; charset=utf-8", PAGE.encode())
            return
        if path == "/health":
            self._send_bytes("application/json", json.dumps({"status": "ok"}).encode())
            return
        if path == "/stream.mjpg":
            self._stream_video()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _send_bytes(self, content_type: str, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream_video(self) -> None:
        server = cast(CaptureServer, self.server)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()

        sequence = 0
        try:
            while True:
                sequence, frame = server.wait_for_frame(sequence)
                if frame is None:
                    continue
                header = (
                    f"--{BOUNDARY}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode()
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


def build_ffmpeg_command(*, device: str, size: str, fps: int, input_format: str) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "v4l2",
        "-input_format", input_format,
        "-video_size", size,
        "-framerate", str(fps),
        "-i", device,
        "-an",
        "-c:v", "copy",
        "-f", "image2pipe",
        "pipe:1",
    ]


def probe_capture(command: list[str], *, timeout: float = 10) -> None:
    probe = [*command]
    output_index = probe.index("-c:v")
    probe[output_index:] = ["-frames:v", "1", "-f", "null", "-"]
    result = subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "Unable to read video capture device")


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a V4L2 FPGA HDMI capture as MJPEG")
    parser.add_argument("--device", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--size", default="640x480")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--input-format", default="mjpeg")
    parser.add_argument("--skip-probe", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed")
    if not Path(args.device).exists():
        raise SystemExit(f"Capture device does not exist: {args.device}")

    command = build_ffmpeg_command(
        device=args.device,
        size=args.size,
        fps=args.fps,
        input_format=args.input_format,
    )
    if not args.skip_probe:
        probe_capture(command)

    server = CaptureServer((args.host, args.port), Handler, ffmpeg_command=command)
    server.start_capture()

    def request_shutdown(_signum, _frame) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    LOG.info("HDMI capture UI: http://%s:%d/ device=%s size=%s fps=%d", args.host, args.port, args.device, args.size, args.fps)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        server.stop_capture()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    main()
