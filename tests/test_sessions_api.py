import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fpga_demo_platform.api import create_app
from fpga_demo_platform.sessions import SessionManager
from fpga_demo_platform.thermal import ThermalStatus
from tests.fakes import FakeBoardWiper, FakeThermalGuard, SequenceThermalGuard


def fake_start_demo_session(demo, session_id, artifact_dir, emit_log):
    emit_log("program_board", "stdout", "fpga-demo: programmed PL")
    return {"demo_id": demo.id, "port": 8765, "access_url": f"/api/sessions/{session_id}/demo/"}


@pytest.fixture(autouse=True)
def fake_runtime_start(monkeypatch):
    import fpga_demo_platform.sessions as sessions_module

    monkeypatch.setattr(sessions_module, "start_demo_session", fake_start_demo_session)


def make_client(tmp_path, *, thermal_guard=None, board_wiper=None):
    manager = SessionManager(
        tmp_path / "sessions.sqlite3",
        tmp_path / "sessions",
        thermal_guard=thermal_guard or FakeThermalGuard(),
        board_wiper=board_wiper,
    )
    return TestClient(create_app(session_manager=manager)), manager


def test_public_api_uses_sessions_not_jobs(tmp_path):
    client, _ = make_client(tmp_path)

    assert client.post("/api/jobs", json={"project_id": "ece338-gpgpu-nbody-3d"}).status_code == 404
    assert client.get("/api/jobs").status_code == 404
    assert client.post("/api/worker/run-next").status_code == 404
    assert client.get("/api/status?refresh=true").status_code == 422


def test_create_session_auto_starts_when_board_is_free(tmp_path, monkeypatch):
    import fpga_demo_platform.sessions as sessions_module

    monkeypatch.setattr(sessions_module, "start_demo_session", fake_start_demo_session)
    client, _ = make_client(tmp_path)

    first = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.1"})

    assert first.status_code == 201
    assert first.json()["state"] == "active"
    assert first.json()["access"]["url"] == f"/api/sessions/{first.json()['id']}/demo/"
    assert {entry["message"] for entry in first.json()["startup_logs"]} >= {
        "pausing thermal reader while programming uses JTAG",
        "fpga-demo: programmed PL",
    }


def test_create_session_grants_only_one_hardware_owner(tmp_path, monkeypatch):
    import fpga_demo_platform.sessions as sessions_module

    monkeypatch.setattr(sessions_module, "start_demo_session", fake_start_demo_session)
    client, _ = make_client(tmp_path)

    first = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.1"})
    second = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.2"})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["state"] == "active"
    assert first.json()["owner_token"]
    assert first.json()["queue_position"] is None
    assert first.json()["lease"]["remaining_seconds"] > 0
    assert second.json()["state"] == "queued"
    assert second.json()["queue_position"] == 1

    status = client.get("/api/status").json()
    assert status["board"]["locked_by_session_id"] == first.json()["id"]
    assert status["sessions"]["active_session_id"] == first.json()["id"]
    assert status["sessions"]["queued"] == 1


def test_release_active_session_auto_starts_next_waiting_session(tmp_path, monkeypatch):
    import fpga_demo_platform.sessions as sessions_module

    monkeypatch.setattr(sessions_module, "start_demo_session", fake_start_demo_session)
    client, _ = make_client(tmp_path)
    first = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.1"}).json()
    second = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.2"}).json()

    released = client.delete(f"/api/sessions/{first['id']}", headers={"x-session-token": first["owner_token"]})

    assert released.status_code == 200
    assert released.json()["state"] == "released"
    promoted = client.get(f"/api/sessions/{second['id']}").json()
    assert promoted["state"] == "active"
    assert promoted["queue_position"] is None
    assert promoted["lease"]["remaining_seconds"] > 0


def test_session_submission_blocks_when_thermal_unavailable(tmp_path):
    client, _ = make_client(tmp_path, thermal_guard=FakeThermalGuard(available=False, reason="too hot"))

    response = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"})

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "hardware_unavailable"
    assert "too hot" in response.text


def test_same_requester_cannot_hold_or_queue_multiple_sessions(tmp_path):
    client, _ = make_client(tmp_path)

    first = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.50"})
    second = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.50"})

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["detail"]["error"]["code"] == "session_limit"


def test_session_request_rejects_unknown_fields_and_project_ids(tmp_path):
    client, _ = make_client(tmp_path)

    assert client.post("/api/sessions", json={"project_id": "missing"}).status_code == 404
    response = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d", "uart_port": "/dev/ttyUSB0"})
    assert response.status_code == 422


def test_no_explicit_start_endpoint_and_owner_can_extend_release_session(tmp_path, monkeypatch):
    import fpga_demo_platform.sessions as sessions_module

    monkeypatch.setattr(sessions_module, "start_demo_session", fake_start_demo_session)
    client, _ = make_client(tmp_path)
    session = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}).json()

    assert client.post(f"/api/sessions/{session['id']}/start", headers={"x-session-token": session["owner_token"]}).status_code == 404
    assert session["state"] == "active"
    assert session["access"]["url"] == f"/api/sessions/{session['id']}/demo/"
    logs = session["startup_logs"]
    assert {entry["message"] for entry in logs} >= {
        "pausing thermal reader while programming uses JTAG",
        "fpga-demo: programmed PL",
    }

    assert client.post(f"/api/sessions/{session['id']}/extend").status_code == 403
    assert client.delete(f"/api/sessions/{session['id']}").status_code == 403
    assert client.delete(f"/api/sessions/{session['id']}", headers={"x-session-token": session["owner_token"]}).status_code == 200


def test_websocket_disconnect_cancels_queued_session(tmp_path, monkeypatch):
    import fpga_demo_platform.sessions as sessions_module

    monkeypatch.setattr(sessions_module, "start_demo_session", fake_start_demo_session)
    client, manager = make_client(tmp_path)
    first = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.1"}).json()
    second = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}, headers={"x-forwarded-for": "198.51.100.2"}).json()
    assert second["state"] == "queued"

    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "subscribe_session", "session_id": second["id"], "logs": True})
        assert ws.receive_json()["type"] == "session.snapshot"

    cancelled = manager.get(second["id"])
    assert cancelled.state == "cancelled"
    assert cancelled.error == "owner_disconnected"
    assert manager.get(first["id"]).state == "active"


def test_session_artifacts_are_manifest_scoped(tmp_path):
    client, manager = make_client(tmp_path)
    session = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"}).json()
    manager.publish_artifact(session["id"], "session.log", "log", "hello\n")

    artifact = client.get(f"/api/sessions/{session['id']}/artifacts/session.log")
    traversal = client.get(f"/api/sessions/{session['id']}/artifacts/../sessions.sqlite3")

    assert artifact.status_code == 200
    assert artifact.text == "hello\n"
    assert traversal.status_code in {400, 404}


def test_websocket_streams_session_events(tmp_path):
    client, _ = make_client(tmp_path)

    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "subscribe", "channels": ["queue", "sessions", "board"]})
        assert ws.receive_json()["type"] == "subscribed"
        snapshot_types = {ws.receive_json()["type"] for _ in range(2)}
        assert "queue.snapshot" in snapshot_types
        assert "board.status" in snapshot_types
        created = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"})
        assert created.status_code == 201
        events = [ws.receive_json()["type"] for _ in range(3)]
        assert "session.created" in events
        assert "queue.changed" in events
        assert "board.status" in events


def test_board_monitor_marks_active_session_failed_when_thermal_becomes_unsafe(tmp_path):
    guard = SequenceThermalGuard([
        ThermalStatus(True, 45.0, 75.0, None, "2026-08-12T00:00:00+00:00"),
        ThermalStatus(False, 82.0, 75.0, "too hot", "2026-08-12T00:00:10+00:00"),
    ])
    wiper = FakeBoardWiper()
    _, manager = make_client(tmp_path, thermal_guard=guard, board_wiper=wiper)
    session = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-a")

    status = manager.check_board_safety()

    failed = manager.get(session.id)
    assert status["thermal"]["available"] is False
    assert failed.state == "failed"
    assert failed.error == "thermal lockout: too hot"
    assert wiper.calls == 1


def test_board_monitor_does_not_wipe_board_when_thermal_is_safe(tmp_path):
    wiper = FakeBoardWiper()
    _, manager = make_client(tmp_path, thermal_guard=FakeThermalGuard(), board_wiper=wiper)
    manager.request_session("ece338-gpgpu-nbody-3d", requester="user-a")

    manager.check_board_safety()

    assert wiper.calls == 0


def test_board_monitor_wipes_board_on_unavailable_transition_even_without_active_session(tmp_path):
    guard = SequenceThermalGuard([
        ThermalStatus(False, 82.0, 75.0, "too hot", "2026-08-12T00:00:10+00:00"),
        ThermalStatus(False, 83.0, 75.0, "still hot", "2026-08-12T00:00:20+00:00"),
        ThermalStatus(True, 55.0, 75.0, None, "2026-08-12T00:00:30+00:00"),
        ThermalStatus(False, 82.0, 75.0, "too hot again", "2026-08-12T00:00:40+00:00"),
    ])
    wiper = FakeBoardWiper()
    _, manager = make_client(tmp_path, thermal_guard=guard, board_wiper=wiper)

    manager.check_board_safety()
    manager.check_board_safety()
    manager.check_board_safety()
    manager.check_board_safety()

    assert wiper.calls == 2


def test_board_monitor_keeps_queued_sessions_queued_during_thermal_lockout(tmp_path):
    guard = SequenceThermalGuard([
        ThermalStatus(True, 45.0, 75.0, None, "2026-08-12T00:00:00+00:00"),
        ThermalStatus(True, 46.0, 75.0, None, "2026-08-12T00:00:01+00:00"),
        ThermalStatus(False, 82.0, 75.0, "too hot", "2026-08-12T00:00:10+00:00"),
    ])
    _, manager = make_client(tmp_path, thermal_guard=guard)
    first = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-a")
    second = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-b")

    manager.check_board_safety()

    assert manager.get(first.id).state == "failed"
    assert manager.get(second.id).state == "queued"


def test_board_monitor_promotes_queued_session_after_thermal_recovery(tmp_path):
    guard = SequenceThermalGuard([
        ThermalStatus(True, 45.0, 75.0, None, "2026-08-12T00:00:00+00:00"),
        ThermalStatus(True, 46.0, 75.0, None, "2026-08-12T00:00:01+00:00"),
        ThermalStatus(False, 82.0, 75.0, "too hot", "2026-08-12T00:00:10+00:00"),
        ThermalStatus(True, 55.0, 75.0, None, "2026-08-12T00:00:20+00:00"),
    ])
    _, manager = make_client(tmp_path, thermal_guard=guard)
    first = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-a")
    second = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-b")

    manager.check_board_safety()
    manager.check_board_safety()

    assert manager.get(first.id).state == "failed"
    assert manager.get(second.id).state == "active"


def test_release_does_not_promote_queued_session_when_cached_thermal_is_unsafe(tmp_path):
    guard = FakeThermalGuard(available=True, temperature_c=45.0)
    _, manager = make_client(tmp_path, thermal_guard=guard)
    first = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-a")
    second = manager.request_session("ece338-gpgpu-nbody-3d", requester="user-b")
    guard._status = ThermalStatus(False, 82.0, 75.0, "too hot", "2026-08-12T00:00:10+00:00")

    manager.release(first.id)

    assert manager.get(second.id).state == "queued"


def test_finished_session_history_is_purged_by_age_and_removes_artifacts(tmp_path):
    _, manager = make_client(tmp_path)
    old_dir = tmp_path / "sessions" / "sess_old"
    old_dir.mkdir(parents=True)
    (old_dir / "session.log").write_text("old", encoding="utf-8")
    old_time = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, project_id, demo_id, state, requester, created_at, released_at, artifact_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sess_old", "ece338-gpgpu-nbody-3d", "gpgpu-nbody", "released", "old", old_time, old_time, str(old_dir)),
        )
        conn.execute(
            "INSERT INTO artifacts (session_id, name, kind, path, content_type) VALUES (?, ?, ?, ?, ?)",
            ("sess_old", "session.log", "log", str(old_dir / "session.log"), "text/plain"),
        )

    removed = manager.purge_history(retention_seconds=24 * 60 * 60, max_finished=200)

    assert removed == 1
    assert not old_dir.exists()
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE id = 'sess_old'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM artifacts WHERE session_id = 'sess_old'").fetchone()[0] == 0


def test_finished_session_history_is_capped_by_count(tmp_path):
    _, manager = make_client(tmp_path)
    now = datetime.now(UTC)
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as conn:
        for idx in range(3):
            when = (now + timedelta(seconds=idx)).isoformat()
            conn.execute(
                """
                INSERT INTO sessions (id, project_id, demo_id, state, requester, created_at, released_at, artifact_dir)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (f"sess_{idx}", "ece338-gpgpu-nbody-3d", "gpgpu-nbody", "released", str(idx), when, when, str(tmp_path / "sessions" / f"sess_{idx}")),
            )

    removed = manager.purge_history(retention_seconds=365 * 24 * 60 * 60, max_finished=2)

    assert removed == 1
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as conn:
        ids = {row[0] for row in conn.execute("SELECT id FROM sessions")}
    assert ids == {"sess_1", "sess_2"}
