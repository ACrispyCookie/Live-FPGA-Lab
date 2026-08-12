from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


DemoKind = Literal["zynq-ps-pl"]


@dataclass(frozen=True)
class Demo:
    id: str
    name: str
    kind: DemoKind
    board: str
    summary: str

    def validate_input(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(payload or {})
        allowed = {"dataset", "steps_per_frame", "fps"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unsupported input field(s): {', '.join(unknown)}")

        dataset = payload.get("dataset", "default")
        if not isinstance(dataset, str) or not dataset:
            raise ValueError("dataset must be a non-empty string")

        steps_per_frame = payload.get("steps_per_frame", 1)
        if not isinstance(steps_per_frame, int) or not 1 <= steps_per_frame <= 10240:
            raise ValueError("steps_per_frame must be an integer from 1 to 10240")

        fps = payload.get("fps", 12.0)
        if not isinstance(fps, int | float) or not 1.0 <= float(fps) <= 60.0:
            raise ValueError("fps must be a number from 1 to 60")

        return {
            "dataset": dataset,
            "steps_per_frame": steps_per_frame,
            "fps": float(fps),
        }


GPGPU_NBODY = Demo(
    id="gpgpu-nbody",
    name="GPGPU n-body simulator",
    kind="zynq-ps-pl",
    board="HelloFPGA ZYNQ7000",
    summary="Interactive n-body simulation running through the ZYNQ PS/PL GPGPU demo stack.",
)

DEMOS: dict[str, Demo] = {GPGPU_NBODY.id: GPGPU_NBODY}


def get_demo(demo_id: str) -> Demo:
    try:
        return DEMOS[demo_id]
    except KeyError as exc:
        raise KeyError(f"unknown demo '{demo_id}'") from exc


def list_demos() -> list[Demo]:
    return list(DEMOS.values())
