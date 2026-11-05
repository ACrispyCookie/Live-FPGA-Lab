from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


# The triangle kernel runs once on the GPGPU and the frame stays on screen.
# The host ELF is built with software.host.autorun (ECE338 GPGPU repo), so
# it draws on HDMI from boot without UART input; the session shows the
# capture card, like the DVD demo.
DEMO_DEFINITION = {
    "id": "gpgpu-triangle",
    "name": "GPGPU triangle",
    "description": "The GPGPU rasterizes one triangle into the framebuffer, shown live over HDMI.",
    "bitstream": "bitstream/gpgpu_platform.bit",
    "ps7_init_tcl": "boot/ps7_init.tcl",
    "elf": "boot/gpgpu_host.elf",
}


def _hdmi_capture_demo():
    """The DVD demo's definition module, whose session streams the capture card."""
    root = next(Path(__file__).resolve().parent.parent.glob("*dvd-logo-video"))
    spec = importlib.util.spec_from_file_location(
        "gpgpu_triangle_hdmi_capture", root / "demo_definition.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the HDMI capture demo")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, root


def start_session(*, demo, session_id: str) -> dict[str, Any]:
    capture, root = _hdmi_capture_demo()
    runtime = capture.start_session(demo=SimpleNamespace(root=root), session_id=session_id)
    runtime["stop"] = capture.stop_session
    return runtime


def stop_session(runtime: dict[str, Any]) -> None:
    runtime["stop"](runtime)
