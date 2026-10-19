from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_api.video import VideoConfig, VideoGate, VideoService, build_ffmpeg_command, create_video_router


class FakeVideoService:
    def __init__(self, enabled: bool):
        self.gate = type("Gate", (), {"enabled": lambda self: enabled})()
        self.tokens = set()

    def acquire_viewer(self):
        token = object()
        self.tokens.add(token)
        return token

    def release_viewer(self, token):
        self.tokens.discard(token)

    def viewer_active(self, token):
        return token in self.tokens and self.gate.enabled()

    def wait_for_frame(self, after, timeout=5):
        return after, None

    async def mjpeg_stream(self):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8test\xff\xd9\r\n"


def _client(service: FakeVideoService) -> TestClient:
    app = FastAPI()
    app.include_router(create_video_router(service))
    return TestClient(app)


def test_video_gate_is_disabled_until_cli_enables_it(tmp_path: Path):
    marker = tmp_path / "video-enabled"
    gate = VideoGate(marker)

    assert gate.enabled() is False
    gate.enable()
    assert gate.enabled() is True
    gate.disable()
    assert gate.enabled() is False


def test_webrtc_ice_is_not_trapped_in_docker_bridge_network():
    compose = (Path(__file__).parent.parent / 'docker-compose.yml').read_text()
    web_api = compose.split('  web-api:\n', 1)[1].split('\nvolumes:', 1)[0]
    assert 'network_mode: host' in web_api
    assert '\n    ports:' not in web_api
    config = (Path(__file__).parent.parent / 'go2rtc.yaml').read_text()
    assert '${WEBRTC_MEDIA_PORT:8555}' in config
    assert '${WEBRTC_PUBLIC_HOST:stun}' in config
    assert '127.0.0.1:1984' in config
    assert 'listen: "127.0.0.1:8554"' in config  # FFmpeg integration uses internal RTSP
    assert '#video=h264' in config
    assert 'libx264' in config


def test_video_transport_default_is_configurable(monkeypatch):
    monkeypatch.delenv('WEB_API_VIDEO_TRANSPORT', raising=False)
    assert VideoConfig.from_env().transport == 'webrtc'
    monkeypatch.setenv('WEB_API_VIDEO_TRANSPORT', 'webrtc')
    assert VideoConfig.from_env().transport == 'webrtc'
    monkeypatch.setenv('WEB_API_VIDEO_TRANSPORT', 'mjpeg')
    assert VideoConfig.from_env().transport == 'mjpeg'
    monkeypatch.setenv('WEB_API_VIDEO_TRANSPORT', 'unsupported')
    import pytest
    with pytest.raises(ValueError, match='WEB_API_VIDEO_TRANSPORT'):
        VideoConfig.from_env()


def test_disabled_video_endpoint_is_not_exposed():
    with _client(FakeVideoService(enabled=False)) as client:
        assert client.get("/video").status_code == 404
        assert client.get("/video/stream.mjpg").status_code == 404
        assert client.get("/video/webrtc").status_code == 404
        assert client.post("/video/webrtc/offer", json={"sdp": "invalid", "type": "offer"}).status_code == 404


def test_enabled_video_endpoint_serves_page_and_mjpeg_stream():
    with _client(FakeVideoService(enabled=True)) as client:
        page = client.get("/video")
        assert page.status_code == 200
        assert "video.src = '/video/stream.mjpg'" in page.text
        assert "Live FPGA video" in page.text
        assert 'id="signal-status"' in page.text
        assert 'No visible video' in page.text
        assert 'getImageData' in page.text
        assert 'Visible video' in page.text
        assert 'id="transport"' in page.text
        assert page.text.index('id="signal-status"') < page.text.index('id="transport"')
        assert "? requested : 'webrtc'" in page.text
        assert 'RTCPeerConnection' in page.text
        assert "video/h264" in page.text
        assert 'transportError' in page.text
        assert "'/video/webrtc/offer'" in page.text
        assert client.get('/video/webrtc').status_code == 404

        stream = client.get("/video/stream.mjpg")
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("multipart/x-mixed-replace")
        assert b"\xff\xd8test\xff\xd9" in stream.content


def test_ffmpeg_command_reencodes_raw_v4l2_but_can_copy_mjpeg():
    raw = build_ffmpeg_command(
        device="/dev/fpga-video",
        size="640x480",
        fps=30,
        input_format="yuyv422",
    )
    mjpeg = build_ffmpeg_command(
        device="/dev/fpga-video",
        size="640x480",
        fps=60,
        input_format="mjpeg",
    )

    assert ["-c:v", "mjpeg", "-q:v", "5"] == raw[-7:-3]
    assert ["-c:v", "copy"] == mjpeg[-5:-3]
    assert raw[-3:] == ["-f", "image2pipe", "pipe:1"]
    assert mjpeg[-3:] == ["-f", "image2pipe", "pipe:1"]


def test_webrtc_offer_is_gated_and_proxied_only_to_local_go2rtc():
    calls = []
    def answer(request):
        calls.append(request)
        return httpx.Response(200, json={'sdp': 'answer-sdp', 'type': 'answer'})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    app = FastAPI()
    app.include_router(create_video_router(FakeVideoService(enabled=True), webrtc_client=upstream))
    with TestClient(app) as client:
        response = client.post('/video/webrtc/offer', json={'sdp': 'offer-sdp', 'type': 'offer'})
        assert response.status_code == 200, response.text
        assert response.json() == {'sdp': 'answer-sdp', 'type': 'answer'}
        assert len(calls) == 1
        assert str(calls[0].url) == 'http://127.0.0.1:1984/api/webrtc?src=fpga'
        assert json.loads(calls[0].content) == {'sdp': 'offer-sdp', 'type': 'offer'}
    asyncio.run(upstream.aclose())


def test_disabling_gate_stops_capture_even_if_viewer_cleanup_is_blocked(tmp_path: Path):
    class FakeCapture:
        def __init__(self):
            self.stop_calls = 0

        def start(self):
            pass

        def stop(self):
            self.stop_calls += 1

    gate = VideoGate(tmp_path / "video-enabled")
    gate.enable()
    capture = FakeCapture()
    service = VideoService(
        VideoConfig(enable_file=gate.marker),
        capture=capture,
        start_monitor=False,
    )

    # A real viewer owns capture; disabling an idle gate need not stop it.
    service._viewer_opened()
    gate.disable()
    service.sync_enabled_state()

    assert capture.stop_calls == 1
