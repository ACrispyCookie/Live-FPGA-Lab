from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


# The ripple kernel runs back to back on the GPGPU, one frame per run.
# The host ELF is built with software.host.autorun (ECE338 GPGPU repo), so
# it draws on HDMI from boot without UART input; the session shows the
# capture card, like the DVD demo.
DEMO_DEFINITION = {
    "id": "gpgpu-ripple",
    "name": "GPGPU ripple animation",
    "description": "The GPGPU renders an animated ripple frame after frame, shown live over HDMI.",
    "bitstream": "bitstream/gpgpu_platform.bit",
    "ps7_init_tcl": "boot/ps7_init.tcl",
    "elf": "boot/gpgpu_host.elf",
}


def _hdmi_capture_demo():
    """The DVD demo's definition module, whose session streams the capture card."""
    root = next(Path(__file__).resolve().parent.parent.glob("*dvd-logo-video"))
    spec = importlib.util.spec_from_file_location(
        "gpgpu_ripple_hdmi_capture", root / "demo_definition.py")
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
