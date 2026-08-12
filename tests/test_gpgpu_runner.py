from pathlib import Path

from fpga_demo_platform.demos import get_demo
from fpga_demo_platform.runners import build_gpgpu_nbody_command, run_gpgpu_nbody


def test_build_gpgpu_nbody_command_points_at_curated_demo_tree(tmp_path):
    root = tmp_path / "demo-root"
    command = build_gpgpu_nbody_command(
        root=root,
        port="/dev/ttyUSB0",
        dataset="default",
        steps_per_frame=3,
        baud=115200,
        kernel_calls=2,
    )

    assert command[1:3] == [str(root / "programs" / "fpga_run.py"), "-p"]
    assert Path(command[0]).name.startswith("python")
    assert "nbody-3d" in command
    assert "--port" in command
    assert "/dev/ttyUSB0" in command
    assert "--kernel-calls" in command
    assert "2" in command
    assert "--steps" in command
    assert "3" in command
    assert "--no-visualize" in command


def test_run_gpgpu_nbody_records_subprocess_output(tmp_path):
    demo_root = tmp_path / "demos" / "gpgpu-nbody"
    (demo_root / "programs").mkdir(parents=True)
    (demo_root / "programs" / "fpga_run.py").write_text("print(\"[SUCCESS] FPGA run loop complete\")")

    result = run_gpgpu_nbody(
        get_demo("gpgpu-nbody"),
        {"dataset": "default", "steps_per_frame": 1, "fps": 12.0},
        tmp_path / "artifacts",
        demo_root=demo_root,
        port="/dev/ttyUSB0",
    )

    assert result["status"] == "completed"
    assert result["adapter"] == "gpgpu-fpga-run"
    assert result["returncode"] == 0
    assert "FPGA run loop complete" in (tmp_path / "artifacts" / "stdout.log").read_text()
