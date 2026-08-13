from fastapi.testclient import TestClient

from fpga_demo_platform.api import create_app
from fpga_demo_platform.sessions import SessionManager
from fpga_demo_platform.web import create_web_app
from tests.fakes import BlockingThermalGuard, FakeThermalGuard


def make_client(tmp_path, *, thermal_guard=None):
    manager = SessionManager(
        tmp_path / "sessions.sqlite3",
        artifacts_dir=tmp_path / "sessions",
        thermal_guard=thermal_guard or FakeThermalGuard(),
    )
    return TestClient(create_app(session_manager=manager))


def test_api_is_json_only_and_does_not_serve_webpage(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"service": "fpga-demo-api", "status": "ok"}
    assert "Live FPGA Lab" not in response.text


def test_static_web_app_embeds_api_base_without_api_routes():
    client = TestClient(create_web_app(api_base="http://fpga-api.local"))

    page = client.get("/")
    assert page.status_code == 200
    assert "Live FPGA Lab" in page.text
    assert "n-body output" in page.text
    assert "EventSource" in page.text
    assert "http://fpga-api.local" in page.text
    assert client.get("/health").json() == {"status": "ok", "service": "web"}
    assert client.get("/api/demos").status_code == 404


def test_api_lists_real_projects_with_runnable_capability(tmp_path):
    client = make_client(tmp_path)

    projects = client.get("/api/projects").json()
    assert {project["source_ref"] for project in projects} >= {"programs/nbody-3d", "programs/mandelbrot", "programs/sobel"}
    assert all("/home/" not in str(project) for project in projects)
    assert client.get("/api/demos").status_code == 404

    runnable = [project for project in projects if project["runnable"]]
    assert [project["id"] for project in runnable] == ["ece338-gpgpu-nbody-3d"]
    assert runnable[0]["lease"]["duration_seconds"] > 0


def test_status_exposes_fast_session_snapshot(tmp_path):
    client = make_client(tmp_path, thermal_guard=FakeThermalGuard(temperature_c=44.5))

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["thermal"]["temperature_c"] == 44.5
    assert payload["sessions"] == {"active_session_id": None, "queued": 0}


def test_status_fast_path_does_not_probe_hardware(tmp_path):
    client = make_client(tmp_path, thermal_guard=BlockingThermalGuard(temperature_c=44.5))

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["thermal"]["temperature_c"] == 44.5


def test_public_status_refresh_is_rejected(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/status?refresh=true")

    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "unsupported_parameter"


def test_session_request_rejects_thermal_unavailable(tmp_path):
    client = make_client(tmp_path, thermal_guard=FakeThermalGuard(available=False, temperature_c=80.0, reason="too hot"))

    response = client.post("/api/sessions", json={"project_id": "ece338-gpgpu-nbody-3d"})

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "hardware_unavailable"
    assert "too hot" in response.text
