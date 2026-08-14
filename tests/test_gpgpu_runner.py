from fpga_demo_platform.demos import get_demo, load_demo_module


def _gpgpu_module():
    return load_demo_module(get_demo("gpgpu-nbody"))


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


def test_start_session_refuses_to_program_when_uart_missing(tmp_path, monkeypatch):
    module = _gpgpu_module()
    demo = get_demo("gpgpu-nbody")
    missing_uart = tmp_path / "missing-ttyUSB0"
    logs = []

    monkeypatch.setattr(module, "DEFAULT_UART_PORT", str(missing_uart))

    try:
        module.start_session(demo=demo, session_id="sess_test", artifact_dir=tmp_path / "artifacts", emit_log=lambda phase, stream, message: logs.append((phase, stream, message)))
    except RuntimeError as exc:
        assert "refusing to program board" in str(exc)
    else:
        raise AssertionError("start_session should fail before programming when UART is missing")

    assert logs == [("preflight", "stderr", f"UART device {missing_uart} is not present; refusing to program board")]
    assert not (tmp_path / "artifacts" / "program-gpgpu.tcl").exists()
