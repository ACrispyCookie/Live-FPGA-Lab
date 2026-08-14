from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FPGAStatus(str, Enum):
    """High-level operational state of an FPGA."""

    OFFLINE = "offline"
    IDLE = "idle"
    PROGRAMMING = "programming"
    RUNNING = "running"
    FAULT = "fault"


class FaultType(str, Enum):
    """Faults that can cause the FPGA to be locked out."""

    OVER_TEMPERATURE = "over_temperature"
    PROGRAMMING_FAILED = "programming_failed"
    COMMUNICATION_LOST = "communication_lost"
    INTERNAL_ERROR = "internal_error"


class FPGAFault(BaseModel):
    """A latched fault associated with an FPGA."""

    type: FaultType
    occurred_at: datetime = Field(default_factory=utc_now)
    temperature_c: float | None = None
    bitstream_id: str | None = None


class FPGATelemetry(BaseModel):
    """Latest telemetry measurements for the FPGA."""

    temperature_c: float | None = None

TemperatureC = Annotated[
    float,
    Field(
        description="Temperature in degrees Celsius",
        ge=-100,
        le=200,
    ),
]


class FPGAState(BaseModel):
    """
    Complete software-visible state of one FPGA device.

    This object describes the FPGA; it does not itself perform hardware
    operations.
    """

    device_id: str
    status: FPGAStatus = FPGAStatus.OFFLINE
    bitstream_id: str | None = None
    telemetry: FPGATelemetry = Field(default_factory=FPGATelemetry)
    faults: list[FPGAFault] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)