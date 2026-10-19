from __future__ import annotations

import importlib.util
import threading
from types import SimpleNamespace
from pathlib import Path
from urllib.request import urlopen
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = next((ROOT / "demos").glob("*dvd-logo-video"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_detects_optional_future_bitstream():
    module = _load("dvd_logo_demo_definition", DEMO_ROOT / "demo_definition.py")

    assert module.DEMO_DEFINITION["id"] == "dvd-logo-video"
    expected = str(module.BITSTREAM) if module.BITSTREAM.is_file() else None
    assert module.DEMO_DEFINITION["bitstream"] == expected
    assert callable(module.start_session)
    assert callable(module.stop_session)


def test_ffmpeg_command_uses_v4l2_mjpeg_passthrough():
    module = _load("dvd_logo_video_stream_command", DEMO_ROOT / "video_stream.py")

    command = module.build_ffmpeg_command(
        device="/dev/fpga-video",
        size="640x480",
        fps=60,
        input_format="mjpeg",
    )

    assert command[:4] == ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    assert ["-f", "v4l2"] == command[4:6]
    assert "/dev/fpga-video" in command
    assert ["-c:v", "copy"] == command[-5:-3]
    assert command[-3:] == ["-f", "image2pipe", "pipe:1"]


def test_ffmpeg_command_reencodes_uncompressed_capture_as_jpeg():
    module = _load("dvd_logo_video_stream_raw_command", DEMO_ROOT / "video_stream.py")

    command = module.build_ffmpeg_command(
        device="/dev/fpga-video",
        size="640x480",
        fps=30,
        input_format="yuyv422",
    )

    assert ["-c:v", "mjpeg", "-q:v", "5"] == command[-7:-3]
    assert command[-3:] == ["-f", "image2pipe", "pipe:1"]


def test_capture_backend_serves_embeddable_page_and_health():
    module = _load("dvd_logo_video_stream_http", DEMO_ROOT / "video_stream.py")
    server = module.CaptureServer(("127.0.0.1", 0), module.Handler, service=SharedService())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            page = response.read().decode()
            assert response.status == 200
            assert "video.src = 'stream.mjpg'" in page
            assert "fetch('webrtc/offer'" in page
            assert 'object-fit: contain' in page
            assert 'max-height: 100dvh' in page
            assert 'value="webrtc"' in page
            assert page.index('id="signal-status"') < page.index('id="transport"')
            assert "? requested : 'webrtc'" in page
            assert "fetch('health'" in page
            assert "setInterval(keepSessionAlive, 20000)" in page

        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert response.status == 200
            assert response.read() == b'{"status": "ok"}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

def test_standalone_viewer_does_not_send_demo_presence_heartbeat():
    from web_api.video import render_video_page

    page = render_video_page()
    assert "fetch('health'" not in page


def test_demo_webrtc_offer_is_session_local(monkeypatch):
    module = _load('dvd_logo_webrtc_http', DEMO_ROOT / 'video_stream.py')
    received = []
    class Answer:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"type":"answer","sdp":"remote"}'
    def fake_open(request, timeout):
        received.append((request.full_url, request.data, timeout))
        return Answer()
    monkeypatch.setattr(module, 'urlopen', fake_open)
    server = module.CaptureServer(('127.0.0.1', 0), module.Handler, service=SharedService())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f'http://127.0.0.1:{server.server_address[1]}/webrtc/offer',
                          data=b'{"type":"offer","sdp":"local"}',
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=2) as response:
            assert response.read() == b'{"type": "answer", "sdp": "remote"}'
        assert received[0][0] == 'http://127.0.0.1:1984/api/webrtc?src=fpga'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class SharedService:
    def __init__(self, *, frames=True):
        self.frames = frames
        self.leases = set()
        self.sequence = 0

    def acquire_demo(self):
        token = object()
        self.leases.add(token)
        return token

    def release_demo(self, token):
        self.leases.discard(token)

    def wait_for_frame(self, after, timeout=5):
        if not self.frames or timeout == 0:
            return self.sequence, None
        self.sequence = max(after, self.sequence) + 1
        return self.sequence, b'\xff\xd8frame\xff\xd9'


def test_demo_server_uses_shared_capture_lease():
    module = _load('dvd_shared_capture', DEMO_ROOT / 'video_stream.py')
    service = SharedService()
    server = module.CaptureServer(('127.0.0.1', 0), module.Handler, service=service)
    try:
        server.start_capture()
        assert len(service.leases) == 1
        assert server.wait_for_frame(0)[1] == b'\xff\xd8frame\xff\xd9'
        server.stop_capture()
        server.stop_capture()
        assert not service.leases
    finally:
        server.server_close()


def test_capture_start_failure_releases_lease():
    module = _load('dvd_shared_capture_failure', DEMO_ROOT / 'video_stream.py')
    service = SharedService(frames=False)
    server = module.CaptureServer(('127.0.0.1', 0), module.Handler, service=service)
    try:
        with pytest.raises(RuntimeError, match='frame'):
            server.start_capture()
        assert not service.leases
    finally:
        server.server_close()


def test_demo_session_uses_in_process_shared_service(monkeypatch):
    import web_api.video as video
    module = _load('dvd_shared_session', DEMO_ROOT / 'demo_definition.py')
    service = SharedService()
    monkeypatch.setattr(video, 'get_video_service', lambda: service, raising=False)
    monkeypatch.setattr(module, '_validate_capture_device', lambda device: None)
    monkeypatch.setattr(module.shutil, 'which', lambda command: '/usr/bin/ffmpeg')
    monkeypatch.setattr(module, 'HTTP_PORT', None)
    runtime = module.start_session(demo=SimpleNamespace(root=DEMO_ROOT), session_id='test')
    try:
        assert 'process' not in runtime
        assert len(service.leases) == 1
        with urlopen(runtime['backend'] + '/', timeout=2) as response:
            assert response.status == 200
        with urlopen(runtime['backend'] + '/stream.mjpg', timeout=2) as response:
            assert b'\xff\xd8frame\xff\xd9' in response.read(100)
    finally:
        module.stop_session(runtime)
    assert not service.leases
    assert not runtime['thread'].is_alive()
