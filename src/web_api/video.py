from __future__ import annotations

import anyio
import httpx
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse


logger = logging.getLogger("video")
BOUNDARY = "frame"

VIDEO_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FPGA video output</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; background: #05070a; }
    body { position: relative; min-height: 100vh; min-height: 100dvh; overflow: hidden; }
    img, video { display: block; position: absolute; inset: 0; width: 100%; height: 100%;
      max-width: 100vw; max-height: 100vh; max-height: 100dvh; object-fit: contain; }
    [hidden] { display: none !important; }
    .controls { position: absolute; z-index: 2; top: 14px; left: 14px;
      display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
    .badge { display: flex; align-items: center; gap: 8px;
      padding: 7px 10px; border: 1px solid #30363d; border-radius: 999px;
      background: rgb(13 17 23 / 82%); color: #e6edf3; font-size: 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #d29922; }
    body.has-signal .dot { background: #3fb950; box-shadow: 0 0 10px #3fb950; }
    .message { position: absolute; inset: 0; display: grid; place-content: center; gap: 8px;
      text-align: center; padding: 24px; background: rgb(5 7 10 / 78%); color: #e6edf3; }
    .message strong { font-size: clamp(22px, 4vw, 32px); }
    .message span { font-size: 14px; color: #aab3bd; }
    body.has-signal .message { display: none; }
    .switch { color: #e6edf3;
      border: 1px solid #30363d; border-radius: 999px; padding: 7px 12px;
      background: rgb(13 17 23 / 82%); font-size: 12px; }
    .switch select { color: inherit; background: #0d1117; border: 0; font: inherit; }
    @media (max-width: 480px) { .controls { top: 10px; left: 10px; } }
  </style>
</head>
<body>
  <img id="capture" alt="Live FPGA video output" />
  <video id="rtc" autoplay playsinline muted hidden></video>
  <div class="controls">
    <div class="badge"><span class="dot"></span><span id="signal-status">Checking video signal</span></div>
    <label class="switch">Transport <select id="transport"><option value="mjpeg">MJPEG</option>
      <option value="webrtc">WebRTC</option></select></label>
  </div>
  <div class="message" role="status"><strong id="signal-message">Waiting for video output…</strong>
    <span>The capture card may take a moment to detect the FPGA HDMI output.</span></div>
  <script>
    const video = document.getElementById('capture');
    const rtc = document.getElementById('rtc');
    const transport = document.getElementById('transport');
    const requested = new URLSearchParams(location.search).get('transport');
    const mode = ['mjpeg', 'webrtc'].includes(requested) ? requested : '__DEFAULT_TRANSPORT__';
    transport.value = mode;
    transport.addEventListener('change', () => {
      location.search = '?transport=' + encodeURIComponent(transport.value);
    });
    if (mode === 'webrtc') { video.hidden = true; rtc.hidden = false; }
    else video.src = '__STREAM_URL__';
    const status = document.getElementById('signal-status');
    const message = document.getElementById('signal-message');
    const probe = document.createElement('canvas');
    probe.width = 96;
    probe.height = 72;
    const context = probe.getContext('2d', { willReadFrequently: true });
    let darkSamples = 0;
    let transportError = '';

    function showSignal(present) {
      document.body.classList.toggle('has-signal', present);
      status.textContent = transportError || (present ? 'Visible video' : 'No visible video');
      message.textContent = transportError || 'No visible video';
    }
    // Some UVC cards output valid, all-black JPEGs while HDMI is absent.
    // This is a picture-content heuristic, not a hardware HDMI-lock reading.
    function inspectFrame() {
      const picture = mode === 'webrtc' ? rtc : video;
      if (!(picture.videoWidth || picture.naturalWidth) || !context) {
        showSignal(false);
        return;
      }
      try {
        context.drawImage(picture, 0, 0, probe.width, probe.height);
        const pixels = context.getImageData(0, 0, probe.width, probe.height).data;
        let visible = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          if (Math.max(pixels[i], pixels[i + 1], pixels[i + 2]) > 40 && ++visible >= 12) break;
        }
        if (visible >= 12) {
          darkSamples = 0;
          showSignal(true);
        } else if (++darkSamples >= 2) {
          showSignal(false);
        }
      } catch (error) {
        // An incomplete/corrupt MJPEG image is not evidence of a signal.
        if (++darkSamples >= 2) showSignal(false);
      }
    }
    video.addEventListener('error', () => {
      transportError = 'Stream disconnected';
      showSignal(false);
      setTimeout(() => { if (mode === 'mjpeg') video.src = '__STREAM_URL__?retry=' + Date.now(); }, 2000);
    });
    video.addEventListener('load', () => { transportError = ''; });
    if (mode === 'webrtc') (async () => {
      const codecs = RTCRtpReceiver.getCapabilities('video')?.codecs || [];
      if (!codecs.some(codec => codec.mimeType.toLowerCase() === 'video/h264')) {
        transportError = 'WebRTC requires H.264 support in this browser';
        showSignal(false);
        return;
      }
      const pc = new RTCPeerConnection();
      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.ontrack = event => { rtc.srcObject = event.streams[0] || new MediaStream([event.track]); };
      pc.onconnectionstatechange = () => {
        if (['failed', 'closed', 'disconnected'].includes(pc.connectionState)) {
          transportError = 'Stream disconnected';
          showSignal(false);
        }
      };
      window.addEventListener('pagehide', () => pc.close(), { once: true });
      try {
        await pc.setLocalDescription(await pc.createOffer());
        const response = await fetch('__OFFER_URL__', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type })
        });
        if (!response.ok) throw new Error('Signaling HTTP ' + response.status);
        await pc.setRemoteDescription(await response.json());
      } catch (error) {
        transportError = 'WebRTC unavailable: ' + error.message;
        showSignal(false);
        pc.close();
      }
    })();
    setInterval(inspectFrame, 500);
  </script>
</body>
</html>
"""


def render_video_page(*, stream_url: str = '/video/stream.mjpg',
                      offer_url: str = '/video/webrtc/offer',
                      transport: str = 'webrtc') -> str:
    """Reuse the responsive viewer inside a demo iframe or /video."""
    return (VIDEO_PAGE.replace('__STREAM_URL__', stream_url)
            .replace('__OFFER_URL__', offer_url)
            .replace('__DEFAULT_TRANSPORT__', transport))

@dataclass(frozen=True)
class VideoConfig:
    enable_file: Path = Path("/run/fpga-video-enabled")
    device: str = "/dev/fpga-video"
    size: str = "640x480"
    fps: int = 60
    input_format: str = "mjpeg"
    transport: str = "webrtc"

    @classmethod
    def from_env(cls) -> "VideoConfig":
        transport = os.environ.get("WEB_API_VIDEO_TRANSPORT", cls.transport).lower()
        if transport not in {"mjpeg", "webrtc"}:
            raise ValueError("WEB_API_VIDEO_TRANSPORT must be mjpeg or webrtc")
        return cls(
            enable_file=Path(os.environ.get("WEB_API_VIDEO_ENABLE_FILE", str(cls.enable_file))),
            device=os.environ.get("WEB_API_VIDEO_DEVICE", os.environ.get("DEMO_VIDEO_DEVICE", cls.device)),
            size=os.environ.get("WEB_API_VIDEO_SIZE", os.environ.get("DEMO_VIDEO_SIZE", cls.size)),
            fps=int(os.environ.get("WEB_API_VIDEO_FPS", os.environ.get("DEMO_VIDEO_FPS", str(cls.fps)))),
            input_format=os.environ.get(
                "WEB_API_VIDEO_INPUT_FORMAT",
                os.environ.get("DEMO_VIDEO_INPUT_FORMAT", cls.input_format),
            ),
            transport=transport,
        )


class VideoGate:
    def __init__(self, marker: Path):
        self.marker = marker

    def enabled(self) -> bool:
        return self.marker.is_file()

    def enable(self) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.touch(exist_ok=True)

    def disable(self) -> None:
        self.marker.unlink(missing_ok=True)


class _VideoService(Protocol):
    gate: VideoGate

    def mjpeg_stream(self) -> AsyncIterator[bytes]: ...
    def acquire_viewer(self) -> object | None: ...
    def release_viewer(self, token: object) -> None: ...
    def viewer_active(self, token: object | None) -> bool: ...
    def wait_for_frame(self, after: int, timeout: float = 5) -> tuple[int, bytes | None]: ...


class _Capture(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def wait_for_frame(self, after: int, timeout: float = 5) -> tuple[int, bytes | None]: ...


class VideoCapture:
    def __init__(self, command: list[str]):
        self.command = command
        self._condition = threading.Condition()
        self._lifecycle_lock = threading.Lock()
        self._latest_frame: bytes | None = None
        self._sequence = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError("Previous video capture is still stopping")
                return
            with self._condition:
                if self._process is not None and self._process.poll() is None:
                    raise RuntimeError("Previous video capture process is still stopping")
                self._latest_frame = None
                self._stop.clear()
            self._thread = threading.Thread(target=self._capture_loop, name="web-video-capture", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        # Serialize the WHOLE transition. The producer only takes _condition,
        # never this lock, so joining it cannot deadlock process publication.
        with self._lifecycle_lock:
            with self._condition:
                self._stop.set()
                self._latest_frame = None
                process = self._process
                self._condition.notify_all()
            thread = self._thread
            if process is not None:
                _stop_process(process)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=3)
            if thread is None or not thread.is_alive():
                self._thread = None
            # Retain a stuck producer's identity; start must not open a second
            # device owner while the old thread is still terminating.

    def wait_for_frame(self, after: int, timeout: float = 5) -> tuple[int, bytes | None]:
        """Return a newer frame only; timeouts/stops never replay cached data."""
        with self._condition:
            self._condition.wait_for(
                lambda: (self._sequence > after and self._latest_frame is not None) or self._stop.is_set(),
                timeout=timeout,
            )
            frame = self._latest_frame if self._sequence > after and not self._stop.is_set() else None
            return self._sequence, frame

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            process = None
            try:
                process = subprocess.Popen(
                    self.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                with self._condition:
                    self._process = process
                # If stop raced Popen, do not enter a blocking pipe read.
                if not self._stop.is_set():
                    self._read_frames(process)
            except OSError:
                logger.exception("Video capture failed; retrying")
            finally:
                if process is not None:
                    _stop_process(process)
                    if process.stdout is not None:
                        process.stdout.close()
                with self._condition:
                    if self._process is process and (process is None or process.poll() is not None):
                        self._process = None
                    self._latest_frame = None
                    self._condition.notify_all()
            if process is not None and process.poll() is None:
                # A bounded shutdown failed. Retain ownership instead of
                # retrying into a second producer on the same device.
                return
            if not self._stop.wait(1):
                logger.warning("Video capture process exited; retrying")

    def _read_frames(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stdout is not None
        buffer = bytearray()
        while not self._stop.is_set():
            # BufferedReader.read(n) waits to fill n bytes: a complete small
            # JPEG can otherwise sit invisible in the pipe until later frames.
            chunk = process.stdout.read1(64 * 1024)
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
                with self._condition:
                    self._latest_frame = frame
                    self._sequence += 1
                    self._condition.notify_all()


class VideoService:
    def __init__(
        self,
        config: VideoConfig | None = None,
        *,
        capture: _Capture | None = None,
        start_monitor: bool = True,
    ):
        self.config = config or VideoConfig.from_env()
        self.gate = VideoGate(self.config.enable_file)
        self.capture = capture or VideoCapture(build_ffmpeg_command(
                device=self.config.device,
                size=self.config.size,
                fps=self.config.fps,
                input_format=self.config.input_format,
            ))
        # This lock covers both ownership changes and capture transitions.
        self._viewer_lock = threading.Lock()
        self._viewer_tokens: set[object] = set()
        self._demo_tokens: set[object] = set()
        self._viewers = 0
        self._capture_running = False
        self._closed = False
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        if start_monitor:
            self._monitor_thread = threading.Thread(
                target=self._monitor_gate,
                name="web-video-gate",
                daemon=True,
            )
            self._monitor_thread.start()

    def acquire_demo(self) -> object:
        """Lease shared capture independently of the standalone /video gate."""
        with self._viewer_lock:
            if self._closed:
                raise RuntimeError("Video service is closed")
            token = object()
            first_demo = not self._demo_tokens
            self._demo_tokens.add(token)
            try:
                # An already-open standalone capture may be locked to the
                # pre-programming (black/no-signal) HDMI input. Reopen V4L2
                # after the first demo has programmed the FPGA.
                if first_demo and self._capture_running:
                    self.capture.stop()
                    self._capture_running = False
                self._sync_locked()
            except BaseException:
                self._demo_tokens.discard(token)
                self._sync_locked()
                raise
            return token

    def release_demo(self, token: object) -> None:
        """Release exactly this lease; duplicate/stale releases are harmless."""
        with self._viewer_lock:
            self._demo_tokens.discard(token)
            self._sync_locked()

    def wait_for_frame(self, after: int, timeout: float = 5) -> tuple[int, bytes | None]:
        return self.capture.wait_for_frame(after, timeout)

    def demo_active(self) -> bool:
        with self._viewer_lock:
            return bool(self._demo_tokens) and not self._closed

    async def internal_mjpeg_stream(self) -> AsyncIterator[bytes]:
        """Loopback media feed; capture ownership belongs to the demo/viewers."""
        sequence = 0
        token = self.acquire_viewer() if self.gate.enabled() else None
        try:
            while self.demo_active() or (token is not None and self.viewer_active(token)):
                sequence, frame = await anyio.to_thread.run_sync(
                    self.wait_for_frame, sequence, 0.2, abandon_on_cancel=True,
                )
                if frame is not None:
                    yield (f'--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n'
                           f'Content-Length: {len(frame)}\r\n\r\n').encode() + frame + b'\r\n'
        finally:
            if token is not None:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(self.release_viewer, token)

    async def mjpeg_stream(self) -> AsyncIterator[bytes]:
        token = None
        sequence = 0
        try:
            # ASGI disconnects cancel the enclosing AnyIO scope repeatedly.
            # Finish acquisition before exposing its token to cancellation.
            with anyio.CancelScope(shield=True):
                token = await anyio.to_thread.run_sync(self._viewer_opened)
            while self._viewer_active(token):
                sequence, frame = await anyio.to_thread.run_sync(
                    self.wait_for_frame, sequence, 0.2, abandon_on_cancel=True,
                )
                if not self._viewer_active(token):
                    break
                if frame is None:
                    continue
                yield (
                    f"--{BOUNDARY}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode() + frame + b"\r\n"
        finally:
            if token is not None:
                # Never hold a cancel scope over yield; only shield cleanup.
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(self._viewer_closed, token)

    def close(self) -> None:
        self._monitor_stop.set()
        with self._viewer_lock:
            self._closed = True
            self._viewer_tokens.clear()
            self._demo_tokens.clear()
            self._sync_locked()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=1)

    def sync_enabled_state(self) -> None:
        with self._viewer_lock:
            self._sync_locked()

    def _sync_locked(self) -> None:
        # Read the gate inside the same lock as the transition: a delayed
        # monitor callback cannot stop capture acquired by newer activity.
        if self._closed or not self.gate.enabled():
            self._viewer_tokens.clear()
        self._viewers = len(self._viewer_tokens)
        needed = bool(self._viewer_tokens or self._demo_tokens) and not self._closed
        if needed and not self._capture_running:
            self.capture.start()
            self._capture_running = True
        elif not needed and self._capture_running:
            self.capture.stop()
            self._capture_running = False

    def _viewer_opened(self) -> object | None:
        with self._viewer_lock:
            if self._closed or not self.gate.enabled():
                self._sync_locked()
                return None
            token = object()
            self._viewer_tokens.add(token)
            try:
                self._sync_locked()
            except BaseException:
                self._viewer_tokens.discard(token)
                self._viewers = len(self._viewer_tokens)
                raise
            return token

    def acquire_viewer(self) -> object | None:
        return self._viewer_opened()

    def release_viewer(self, token: object) -> None:
        self._viewer_closed(token)

    def viewer_active(self, token: object | None) -> bool:
        return self._viewer_active(token)

    def _viewer_active(self, token: object | None) -> bool:
        with self._viewer_lock:
            return token in self._viewer_tokens and self.gate.enabled() and not self._closed

    def _viewer_closed(self, token: object) -> None:
        with self._viewer_lock:
            self._viewer_tokens.discard(token)
            self._sync_locked()

    def _monitor_gate(self) -> None:
        while not self._monitor_stop.wait(0.2):
            self.sync_enabled_state()


_video_service: VideoService | None = None
_video_service_lock = threading.Lock()


def get_video_service() -> VideoService:
    """Lazy process-wide capture owner shared by the API and demo adapters."""
    global _video_service
    with _video_service_lock:
        if _video_service is None:
            _video_service = VideoService()
        return _video_service


def create_video_router(service: _VideoService, *, webrtc_client: httpx.AsyncClient | None = None) -> APIRouter:
    from .webrtc import create_webrtc_router

    router = APIRouter()
    router.include_router(create_webrtc_router(service, webrtc_client))

    @router.get("/video", include_in_schema=False)
    async def video_page() -> HTMLResponse:
        _require_enabled(service)
        default = getattr(getattr(service, "config", None), "transport", "webrtc")
        return HTMLResponse(render_video_page(transport=default), headers={"Cache-Control": "no-store"})

    @router.get('/video/internal/stream.mjpg', include_in_schema=False)
    async def internal_stream(request: Request) -> StreamingResponse:
        if request.client is None or request.client.host not in {'127.0.0.1', '::1'}:
            raise HTTPException(404)
        if not getattr(service, 'demo_active', lambda: False)() and not service.gate.enabled():
            raise HTTPException(404)
        return StreamingResponse(service.internal_mjpeg_stream(),
                                 media_type=f'multipart/x-mixed-replace; boundary={BOUNDARY}',
                                 headers={'Cache-Control': 'no-store'})

    @router.get("/video/stream.mjpg", include_in_schema=False)
    async def video_stream() -> StreamingResponse:
        _require_enabled(service)
        return StreamingResponse(
            service.mjpeg_stream(),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )

    return router


def build_ffmpeg_command(*, device: str, size: str, fps: int, input_format: str) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "v4l2",
        "-input_format", input_format,
        "-video_size", size,
        "-framerate", str(fps),
        "-i", device,
        "-an",
    ]
    if input_format.lower() in {"mjpeg", "mjpg", "jpeg"}:
        command.extend(["-c:v", "copy"])
    else:
        command.extend(["-c:v", "mjpeg", "-q:v", "5"])
    command.extend(["-f", "image2pipe", "pipe:1"])
    return command


def _require_enabled(service: _VideoService) -> None:
    if not service.gate.enabled():
        raise HTTPException(404, "Video endpoint is disabled")


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                logger.error("Video capture did not exit after kill")
    except ProcessLookupError:
        # The producer and stop caller may observe process exit concurrently.
        pass
