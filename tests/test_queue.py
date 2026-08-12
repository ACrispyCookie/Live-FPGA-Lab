from pathlib import Path

from fpga_demo_platform.queue import JobQueue
from tests.fakes import FakeThermalGuard


def successful_runner(demo_id, payload, artifact_dir):
    return {"demo": demo_id, "adapter": "test-runner", "input": payload}


def test_submits_job_and_runs_injected_runner(tmp_path):
    queue = JobQueue(
        tmp_path / "jobs.sqlite3",
        artifacts_dir=tmp_path / "runs",
        runner=successful_runner,
        thermal_guard=FakeThermalGuard(),
    )

    job = queue.submit("gpgpu-nbody", {"dataset": "default", "steps_per_frame": 2}, requester="test-client")
    assert job.status == "queued"

    result = queue.run_next()

    assert result is not None
    assert result.status == "succeeded"
    assert result.demo_id == "gpgpu-nbody"
    assert result.input == {"dataset": "default", "steps_per_frame": 2, "kernel_calls": 1, "fps": 12.0}
    assert result.result["demo"] == "gpgpu-nbody"
    assert result.result["adapter"] == "test-runner"
    assert Path(result.artifact_dir).exists()
    assert (Path(result.artifact_dir) / "summary.json").exists()


def test_queue_blocks_second_concurrent_running_job(tmp_path):
    queue = JobQueue(tmp_path / "jobs.sqlite3", artifacts_dir=tmp_path / "runs", thermal_guard=FakeThermalGuard())

    first = queue.submit("gpgpu-nbody", {"dataset": "default"})
    second = queue.submit("gpgpu-nbody", {"dataset": "wide"})

    claimed = queue.claim_next()
    assert claimed.id == first.id
    assert queue.claim_next() is None

    queue.finish(claimed.id, status="succeeded", result={"ok": True})
    assert queue.claim_next().id == second.id


def test_queue_rejects_submit_when_fpga_is_over_temperature(tmp_path):
    queue = JobQueue(
        tmp_path / "jobs.sqlite3",
        artifacts_dir=tmp_path / "runs",
        thermal_guard=FakeThermalGuard(available=False, temperature_c=80.0, reason="too hot"),
    )

    try:
        queue.submit("gpgpu-nbody", {"dataset": "default"})
    except Exception as exc:  # noqa: BLE001
        assert "too hot" in str(exc)
    else:
        raise AssertionError("submit should fail while thermal guard is unavailable")


def test_thermal_status_cancels_running_jobs(tmp_path):
    guard = FakeThermalGuard()
    queue = JobQueue(tmp_path / "jobs.sqlite3", artifacts_dir=tmp_path / "runs", thermal_guard=guard)
    job = queue.submit("gpgpu-nbody", {"dataset": "default"})
    running = queue.claim_next()
    assert running.id == job.id

    guard._status = FakeThermalGuard(available=False, temperature_c=80.0, reason="too hot")._status
    status = queue.thermal_status(refresh=True)

    assert status["available"] is False
    assert queue.get(job.id).status == "cancelled"
