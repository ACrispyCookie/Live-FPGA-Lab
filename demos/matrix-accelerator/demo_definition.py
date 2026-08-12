from __future__ import annotations

from typing import Any

DEMO = {
    "id": "matrix-accelerator",
    "name": "Matrix Accelerator",
    "kind": "zynq-ps-pl",
    "board": "HelloFPGA ZYNQ7000",
    "summary": "Coming soon: launch a PS/PL matrix benchmark with selectable workloads and live results.",
    "available": False,
    "placeholder": True,
}


def validate_input(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})
