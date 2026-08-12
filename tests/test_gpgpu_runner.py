from pathlib import Path

from fpga_demo_platform.demos import get_demo, load_demo_module


def _gpgpu_module():
    return load_demo_module(get_demo("gpgpu-nbody"))


def test_build_gpgpu_nbody_command_points_at_curated_demo_tree(tmp_path):
    module = _gpgpu_module()
    root = tmp_path / "demo-root"
    command = module.build_gpgpu_nbody_command(
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


def test_build_gpgpu_program_script_downloads_pl_initializes_ps_and_starts_app(tmp_path):
    module = _gpgpu_module()
    root = tmp_path / "demo-root"
    script = module.build_gpgpu_program_script(root=root)

    assert f"fpga -file {root / 'bitstream' / 'gpgpu_system_hello.bit'}" in script
    assert f"source {root / 'boot' / 'ps7_init.tcl'}" in script
    assert "ps7_init" in script
    assert "ps7_post_config" in script
    assert f"dow {root / 'boot' / 'gpgpu_app.elf'}" in script
    assert "con" in script


def test_gpgpu_demo_runner_records_subprocess_output(tmp_path):
    module = _gpgpu_module()
    demo = get_demo("gpgpu-nbody")
    demo_root = tmp_path / "demos" / "gpgpu-nbody"
    (demo_root / "programs").mkdir(parents=True)
    (demo_root / "programs" / "fpga_run.py").write_text("print(\"[SUCCESS] FPGA run loop complete\")")

    result = module.run_gpgpu_nbody(
        demo=demo,
        payload={"dataset": "default", "steps_per_frame": 1, "fps": 12.0},
        artifact_dir=tmp_path / "artifacts",
        demo_root=demo_root,
        port="/dev/ttyUSB0",
        program_board=False,
    )

    assert result["status"] == "completed"
    assert result["adapter"] == "gpgpu-fpga-run"
    assert result["programmed"] is False
    assert result["returncode"] == 0
    assert "FPGA run loop complete" in (tmp_path / "artifacts" / "stdout.log").read_text()
