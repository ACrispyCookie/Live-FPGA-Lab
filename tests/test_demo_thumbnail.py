"""Each demo may ship a thumbnail; the lab serves it and tells the browser where it is."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_api.api import create_api
from web_api.board import BoardManager
from web_api.config import SessionConfig, WebApiConfig
from web_api.demo_loader import DemoDefinition, load_demos
from web_api.sessions import SessionManager


def write_demo(root: Path, demo_id: str, *, thumbnail: bool) -> Path:
    folder = root / demo_id
    folder.mkdir()
    extra = '    "thumbnail": "thumbnail.svg",\n' if thumbnail else ""
    (folder / "demo_definition.py").write_text(
        'DEMO_DEFINITION = {\n    "id": "%s",\n    "name": "Demo %s",\n%s}\n' % (demo_id, demo_id, extra)
    )
    if thumbnail:
        (folder / "thumbnail.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 76"></svg>')
    return folder


def test_loader_reads_thumbnail_path(tmp_path):
    write_demo(tmp_path, "with-thumb", thumbnail=True)
    write_demo(tmp_path, "without", thumbnail=False)
    demos = load_demos(tmp_path)
    assert demos["with-thumb"].thumbnail == tmp_path / "with-thumb" / "thumbnail.svg"
    assert demos["without"].thumbnail is None


def make_board(tmp_path: Path) -> BoardManager:
    with_thumb = write_demo(tmp_path, "with-thumb", thumbnail=True)
    without = write_demo(tmp_path, "without", thumbnail=False)
    demos = {
        "with-thumb": DemoDefinition(id="with-thumb", name="Demo A", root=with_thumb, thumbnail=with_thumb / "thumbnail.svg"),
        "without": DemoDefinition(id="without", name="Demo B", root=without),
        "missing-file": DemoDefinition(id="missing-file", name="Demo C", root=without, thumbnail=without / "nope.svg"),
    }
    return BoardManager(agent=None, config=WebApiConfig(), demos=demos, sessions=SessionManager(SessionConfig()))


def test_public_demo_includes_thumbnail_url_only_when_file_exists(tmp_path):
    board = make_board(tmp_path)
    public = {d["id"]: d for d in (board._public_demo(demo) for demo in board.demos.values())}
    assert public["with-thumb"]["thumbnail_url"] == "/api/demos/with-thumb/thumbnail"
    assert public["without"]["thumbnail_url"] is None
    assert public["missing-file"]["thumbnail_url"] is None


def test_thumbnail_endpoint_serves_file_and_404s(tmp_path):
    board = make_board(tmp_path)
    app = FastAPI()
    app.state.config = WebApiConfig()
    app.include_router(create_api(board, httpx.AsyncClient(), config=WebApiConfig()))
    with TestClient(app) as client:
        ok = client.get("/api/demos/with-thumb/thumbnail")
        assert ok.status_code == 200
        assert ok.headers["content-type"].startswith("image/svg+xml")
        assert ok.headers["cache-control"] == "public, max-age=86400"
        assert ok.text.startswith("<svg")
        assert client.get("/api/demos/without/thumbnail").status_code == 404
        assert client.get("/api/demos/missing-file/thumbnail").status_code == 404
        assert client.get("/api/demos/unknown/thumbnail").status_code == 404
