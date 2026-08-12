from __future__ import annotations

from typing import Any

DEMO = {
    "id": "signal-lab",
    "name": "Signal Processing Lab",
    "kind": "zynq-ps-pl",
    "board": "HelloFPGA ZYNQ7000",
    "summary": "Coming soon: stream small DSP/FFT-style jobs through the board and visualize outputs.",
    "available": False,
    "placeholder": True,
}


def validate_input(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})
