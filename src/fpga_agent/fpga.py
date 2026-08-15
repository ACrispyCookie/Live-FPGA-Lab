from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from dataclasses import dataclass

from pydantic import BaseModel, Field, computed_field
import logging

logger = logging.getLogger(__name__)

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FPGAStatus(str, Enum):
    """High-level operational state of an FPGA."""

    OFFLINE = "offline"
    IDLE = "idle"
    RUNNING = "running"
    FAULT = "fault"


class FPGATelemetry(BaseModel):
    """Latest telemetry measurements for the FPGA."""

    temperature_c: float | None = None
    checked_at: datetime | None = None


class FaultType(str, Enum):
    """Faults that can cause the FPGA to be locked out."""

    OVER_TEMPERATURE = "over_temperature"
    PROGRAMMING_FAILED = "programming_failed"
    COMMUNICATION_LOST = "communication_lost"


@dataclass(frozen=True)
class FaultPolicy:
    blocks_programming: bool


FAULT_POLICIES: dict[FaultType, FaultPolicy] = {
    FaultType.OVER_TEMPERATURE: FaultPolicy(
        blocks_programming=True,
    ),

    FaultType.PROGRAMMING_FAILED: FaultPolicy(
        blocks_programming=False,
    ),

    FaultType.COMMUNICATION_LOST: FaultPolicy(
        blocks_programming=False,
    ),
}


class FPGAFault(BaseModel):
    """A latched fault associated with an FPGA."""

    type: FaultType
    bitstream_id: str | None = None
    telemetry: FPGATelemetry | None = None

class JTAGTargetContext(BaseModel):
    """XSDB target identifiers needed to select one physical FPGA board."""

    cable: str
    fpga_id: str
    fpga_name: str
    core_id: str | None = None
    core_name: str | None = None
    dap_id: str | None = None


class FPGAState(BaseModel):
    """Complete software-visible state of one FPGA device."""

    target_ctx: JTAGTargetContext
    bitstream_id: str | None = None
    telemetry: FPGATelemetry = Field(default_factory=FPGATelemetry)
    faults: list[FPGAFault] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)

    @computed_field
    @property
    def status(self) -> FPGAStatus:
        if any(
            fault.type == FaultType.COMMUNICATION_LOST
            for fault in self.faults
        ): 
            return FPGAStatus.OFFLINE
        elif not self.can_program():
            return FPGAStatus.FAULT
        elif self.bitstream_id:
            return FPGAStatus.RUNNING
        return FPGAStatus.IDLE

    
    @property
    def device_id(self) -> str:
        return self.target_ctx.cable


    def can_program(self) -> bool:
        return not any(
            FAULT_POLICIES[fault.type].blocks_programming
            for fault in self.faults
        )


_FPGA_STATES: dict[str, FPGAState] = {}
_FPGA_LOCK = RLock()


def fpga_states() -> dict[str, FPGAState]:
    """Return a snapshot of all discovered FPGA states keyed by cable/device_id."""

    with _FPGA_LOCK:
        return dict(_FPGA_STATES)


def list_fpgas() -> list[FPGAState]:
    with _FPGA_LOCK:
        return list(_FPGA_STATES.values())


def get_fpga(device_id: str) -> FPGAState:
    with _FPGA_LOCK:
        try:
            return _FPGA_STATES[device_id]
        except KeyError as exc:
            raise KeyError(f"unknown FPGA device {device_id!r}") from exc


def register_fpga(state: FPGAState) -> FPGAState | None:
    updated = state.model_copy(update={"updated_at": utc_now()})
    with _FPGA_LOCK:
        if updated.device_id not in _FPGA_STATES:
            _FPGA_STATES[updated.device_id] = updated
            return updated
    return None


def update_fpga(device_state: FPGAState, **changes) -> FPGAState:
    with _FPGA_LOCK:
        current = _FPGA_STATES[device_state.device_id]
        updated = current.model_copy(update={**changes, "updated_at": utc_now()})
        _FPGA_STATES[current.device_id] = updated
        return updated


def add_fault(device_state: FPGAState, fault_type: FaultType) -> FPGAState:
    with _FPGA_LOCK:
        current = _FPGA_STATES[device_state.device_id]

        if any(
            fault.type == fault_type
            for fault in current.faults
        ):
            return current
        fault = FPGAFault(type=fault_type,
                          bitstream_id=current.bitstream_id, 
                          telemetry=current.telemetry.model_copy()
        )
        updated = current.model_copy(
            update={
                "faults": [*current.faults, fault],
                "updated_at": utc_now(),
            }
        )

        logger.error(
            "A fault has occured on FPGA %s of type %s: %s",
            updated.device_id,
            fault_type,
            updated.telemetry
        )
        _FPGA_STATES[updated.device_id] = updated
        return updated

    
def clear_fault(device_state: FPGAState, fault_type: FaultType) -> FPGAState:
    with _FPGA_LOCK:
        current = _FPGA_STATES[device_state.device_id]

        if not any(
            fault.type == fault_type
            for fault in current.faults
        ):
            return current

        updated = current.model_copy(
            update={
                "faults": [
                    fault
                    for fault in current.faults
                    if fault.type != fault_type
                ],
                "updated_at": utc_now(),
            }
        )

        logger.info(
            "A fault has been cleared on FPGA %s of type %s: %s",
            updated.device_id,
            fault_type,
            updated.telemetry
        )
        _FPGA_STATES[updated.device_id] = updated
        return updated


def register_jtag_discovery(targets: list[JTAGTargetContext]) -> list[FPGAState]:
    """Convert discovered XSDB JTAG targets into stored FPGAState objects."""

    discovered: list[FPGAState] = []
    for target in targets:
        state = FPGAState(
            target_ctx=target,
        )
        registered = register_fpga(state)
        if registered:
            discovered.append(registered)
    return discovered
