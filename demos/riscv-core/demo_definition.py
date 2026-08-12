from __future__ import annotations

from typing import Any

DEMO = {
    "id": "riscv-core",
    "name": "RISC-V Core Bring-up",
    "kind": "zynq-ps-pl",
    "board": "HelloFPGA ZYNQ7000",
    "summary": "Coming soon: run CPU programs, capture traces, and show pipeline/control-plane artifacts.",
    "available": False,
    "placeholder": True,
}


def validate_input(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})
