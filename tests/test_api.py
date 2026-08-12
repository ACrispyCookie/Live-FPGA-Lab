from fastapi.testclient import TestClient

from fpga_demo_platform.api import create_app
from fpga_demo_platform.queue import JobQueue
from tests.fakes import FakeThermalGuard


def successful_runner(demo_id, payload, artifact_dir):
    return {"demo": demo_id, "adapter": "test-runner", "input": payload}


def test_api_lists_gpgpu_demo_and_runs_job(tmp_path):
    queue = JobQueue(
        tmp_path / "jobs.sqlite3",
        artifacts_dir=tmp_path / "runs",
        runner=successful_runner,
        thermal_guard=FakeThermalGuard(),
    )
    client = TestClient(create_app(queue=queue))

    demos = client.get("/api/demos").json()
    assert demos[0] == {
        "id": "gpgpu-nbody",
        "name": "GPGPU n-body simulator",
        "kind": "zynq-ps-pl",
        "board": "HelloFPGA ZYNQ7000",
        "summary": "Interactive n-body simulation running through the ZYNQ PS/PL GPGPU demo stack.",
        "available": True,
        "placeholder": False,
    }
    assert {demo["id"] for demo in demos[1:]} == {"matrix-accelerator", "riscv-core", "signal-lab"}
    assert all(demo["placeholder"] and not demo["available"] for demo in demos[1:])

    submitted = client.post("/api/demos/gpgpu-nbody/run", json={"input": {"steps_per_frame": 4}})
    assert submitted.status_code == 201
    job_id = submitted.json()["id"]

    worker_result = client.post("/api/worker/run-next")
    assert worker_result.status_code == 200
    assert worker_result.json()["status"] == "succeeded"

    fetched = client.get(f"/api/jobs/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["result"]["adapter"] == "test-runner"


def test_api_rejects_invalid_input(tmp_path):
    queue = JobQueue(
        tmp_path / "jobs.sqlite3",
        artifacts_dir=tmp_path / "runs",
        thermal_guard=FakeThermalGuard(),
    )
    client = TestClient(create_app(queue=queue))

    response = client.post("/api/demos/gpgpu-nbody/run", json={"input": {"steps_per_frame": 0}})

    assert response.status_code == 422
    assert "steps_per_frame" in response.text


def test_status_exposes_thermal_guard_and_recent_jobs(tmp_path):
    queue = JobQueue(
        tmp_path / "jobs.sqlite3",
        artifacts_dir=tmp_path / "runs",
        thermal_guard=FakeThermalGuard(temperature_c=44.5),
    )
    client = TestClient(create_app(queue=queue))

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["thermal"]["available"] is True
    assert payload["thermal"]["temperature_c"] == 44.5
    assert payload["jobs"] == []


def test_api_blocks_runs_when_fpga_is_over_temperature(tmp_path):
    queue = JobQueue(
        tmp_path / "jobs.sqlite3",
        artifacts_dir=tmp_path / "runs",
        thermal_guard=FakeThermalGuard(available=False, temperature_c=80.0, reason="too hot"),
    )
    client = TestClient(create_app(queue=queue))

    response = client.post("/api/demos/gpgpu-nbody/run", json={"input": {}})

    assert response.status_code == 503
    assert response.json()["detail"]["thermal"]["available"] is False
    assert "too hot" in response.text
