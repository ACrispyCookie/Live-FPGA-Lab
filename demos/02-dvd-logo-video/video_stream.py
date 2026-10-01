from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from web_api.video import VideoConfig, VideoService, build_ffmpeg_command, render_video_page


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
    img { display: block; width: 100%; height: 100%; object-fit: contain; }
    .badge { position: absolute; top: 14px; left: 14px; display: flex; align-items: center; gap: 8px;
      padding: 7px 10px; border: 1px solid #30363d; border-radius: 999px;
      background: rgb(13 17 23 / 82%); color: #e6edf3; font-size: 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #3fb950; }
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
    """Session-local HTTP view of the web API's shared capture source."""

    daemon_threads = True

    def __init__(self, address, handler, *, service):
        super().__init__(address, handler)
        self.service = service
        self._lease = None
        self._stopping = threading.Event()

    def start_capture(self) -> None:
        if self._lease is not None:
            return
        self._stopping.clear()
        self._lease = self.service.acquire_demo()
        try:
            # Read a new frame, not a cached image from before programming.
            sequence, _ = self.service.wait_for_frame(0, timeout=0)
            _, frame = self.service.wait_for_frame(sequence, timeout=10)
            if frame is None:
                raise RuntimeError("Video capture did not produce a fresh frame")
        except BaseException:
            self.stop_capture()
            raise

    def wait_for_frame(self, after_sequence: int, timeout: float = 1):
        return self.service.wait_for_frame(after_sequence, timeout=timeout)

    def stop_capture(self) -> None:
        self._stopping.set()
        lease, self._lease = self._lease, None
        if lease is not None:
            self.service.release_demo(lease)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"", "/", "/index.html"}:
            self._send_bytes("text/html; charset=utf-8", render_video_page(
                stream_url="stream.mjpg", offer_url="webrtc/offer",
                transport=getattr(getattr(cast(CaptureServer, self.server).service, 'config', None),
                                  'transport', 'webrtc'),
            ).encode())
        elif path == "/health":
            self._send_bytes("application/json", json.dumps({"status": "ok"}).encode())
        elif path == "/stream.mjpg":
            self._stream_video()
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != '/webrtc/offer':
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 100_000:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if payload.get('type') != 'offer' or not isinstance(payload.get('sdp'), str) or not payload['sdp']:
                raise ValueError('Invalid offer')
        except (ValueError, AttributeError):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        try:
            request = Request('http://127.0.0.1:1984/api/webrtc?src=fpga',
                              data=json.dumps(payload).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=20) as response:
                answer = json.load(response)
            if answer.get('type') != 'answer' or not answer.get('sdp'):
                raise ValueError('Invalid media answer')
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            LOG.warning('WebRTC signaling failed: %s', exc)
            self.send_error(HTTPStatus.BAD_GATEWAY)
            return
        self._send_bytes('application/json', json.dumps(answer).encode())

    def _send_bytes(self, content_type: str, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream_video(self) -> None:
        server = cast(CaptureServer, self.server)
        self.connection.settimeout(5)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        sequence = 0
        try:
            while not server._stopping.is_set():
                next_sequence, frame = server.wait_for_frame(sequence)
                if server._stopping.is_set():
                    break
                if frame is None or next_sequence <= sequence:
                    continue
                sequence = next_sequence
                header = (
                    f"--{BOUNDARY}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode()
                self.wfile.write(header + frame + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def log_message(self, format: str, *args) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a V4L2 FPGA HDMI capture as MJPEG")
    parser.add_argument("--device", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--size", default="640x480")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--input-format", default="mjpeg")
    args = parser.parse_args()
    service = VideoService(VideoConfig(
        device=args.device, size=args.size, fps=args.fps, input_format=args.input_format,
    ), start_monitor=False)
    server = CaptureServer((args.host, args.port), Handler, service=service)

    def request_shutdown(_signum, _frame) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    try:
        server.start_capture()
        server.serve_forever(poll_interval=0.2)
    finally:
        server.stop_capture()
        server.server_close()
        service.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    main()
