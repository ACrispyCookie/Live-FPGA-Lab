import logging
from dataclasses import dataclass
import asyncio
import hashlib
from pathlib import Path

from .actions import BoardActions, ActionResult, ActionError
from .fpga import register_jtag_discovery, list_fpgas, update_fpga, add_fault, clear_fault, get_fpga, FPGAState, FPGATelemetry, FaultType

logger = logging.getLogger('agent')

@dataclass(frozen=True)
class AgentConfig:
    discovery_interval_seconds: float = 5.0
    telemetry_interval_seconds: float = 1.0

    over_temperature_c: float = 75.0
    over_temperature_recovery_c: float = 60.0

class Agent:
    def __init__(
        self,
        config: AgentConfig,
    ) -> None:
        self.config = config or AgentConfig()
        self._actions = BoardActions()
        self._running = False
        self._discovery_task: asyncio.Task | None = None
        self._telemetry_task: asyncio.Task | None = None
        self._device_locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        if self._running:
            logger.debug("FPGA agent is already running")
            return
        logger.info("Starting FPGA agent")
        logger.info("Performing initial FPGA discovery")

        # Discover devices
        result = await asyncio.to_thread(
            self._actions.discover_jtag_targets
        )
        if not result.ok:
            logger.error(
                "FPGA agent startup failed: initial discovery failed: %s",
                result.stderr or result.error,
            )
            return
        targets = result.data or []
        if not targets:
            logger.error("FPGA agent startup failed: no FPGA devices were discovered")
            return
        register_jtag_discovery(targets)
        logger.info(
            "Initial FPGA discovery completed successfully: %d device(s) found",
            len(targets),
        )

        # Background tasks
        self._running = True
        self._discovery_task = asyncio.create_task(
            self._discovery_loop(),
            name="fpga-discovery",
        )
        self._telemetry_task = asyncio.create_task(
            self._telemetry_loop(),
            name="fpga-telemetry",
        )
        logger.info("FPGA agent started with discovery and telemetry monitoring enabled")

    async def stop(self) -> None:
        if not self._running:
            return
        logger.info("Stopping FPGA agent")
        self._running = False

        tasks = [
            task
            for task in (
                self._discovery_task,
                self._telemetry_task,
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        self._discovery_task = None
        self._telemetry_task = None
        logger.info("FPGA agent stopped")

    def list_devices(self) -> list[FPGAState]:
        return list_fpgas()


    def get_device(
        self,
        device_id: str,
    ) -> FPGAState:
        return get_fpga(device_id)

    async def program_pl(
        self,
        device_id: str,
        bitstream: str | Path,
    ) -> FPGAState:
        device = get_fpga(device_id)
        if not device.can_program():
            raise RuntimeError(f"FPGA {device_id!r} cannot currently be programmed")
        lock = self._get_device_lock(device_id)

        async with lock:
            # Get current state again after acquiring the lock.
            device = get_fpga(device_id)
            if not device.can_program():
                raise RuntimeError(f"FPGA {device_id!r} cannot currently be programmed")
            logger.info("Programming PL on FPGA %s with %s", device_id, bitstream)
            result = await asyncio.to_thread(self._actions.program_pl, bitstream, device_state=device)

            # State may have changed while the tool was running.
            device = get_fpga(device_id)
            if not result.ok:
                device = add_fault(device, FaultType.PROGRAMMING_FAILED)
                logger.error("PL programming failed on FPGA %s: %s, %s", device_id, result.error, result.stderr)
                raise RuntimeError(result.stderr or "PL programming failed")
            
            bitstream_id = _sha256_file(Path(bitstream).expanduser().resolve())
            device = clear_fault(device,FaultType.PROGRAMMING_FAILED)
            device = clear_fault(device, FaultType.COMMUNICATION_LOST)
            device = update_fpga(device, bitstream_id=bitstream_id)
            logger.info("PL programming completed on FPGA %s (bitstream=%s)", device_id, bitstream_id[:12])
        return device


    async def program_ps(
        self,
        device_id: str,
        *,
        ps7_init_tcl: str | Path,
        elf: str | Path,
        reset_processor: bool = True,
        continue_after_download: bool = True,
    ) -> FPGAState:
        device = get_fpga(device_id)
        if not device.can_program():
            raise RuntimeError(f"FPGA {device_id!r} cannot currently be programmed")
        lock = self._get_device_lock(device_id)

        async with lock:
            # Get current state again after acquiring the lock.
            device = get_fpga(device_id)
            if not device.can_program():
                raise RuntimeError(f"FPGA {device_id!r} cannot currently be programmed")
            logger.info("Programming PS on FPGA %s with %s", device_id, elf)
            result = await asyncio.to_thread(
                self._actions.program_ps,
                device_state=device,
                ps7_init_tcl=ps7_init_tcl,
                elf=elf,
                reset_processor=reset_processor,
                continue_after_download=continue_after_download,
            )

            # State may have changed while the tool was running.
            device = get_fpga(device_id)
            if not result.ok:
                device = add_fault(device, FaultType.PROGRAMMING_FAILED)
                logger.error("PS programming failed on FPGA %s: %s, %s", device_id, result.error, result.stderr)
                raise RuntimeError(result.stderr or "PS programming failed")

            device = clear_fault(device,FaultType.PROGRAMMING_FAILED)
            device = clear_fault(device, FaultType.COMMUNICATION_LOST)
            logger.info("PS programming completed on FPGA %s", device_id)
        return device

    async def reset_board(
        self,
        device_id: str,
    ) -> FPGAState:
        device = get_fpga(device_id)
        lock = self._get_device_lock(device_id)

        async with lock:
            # Get current state again after acquiring the lock.
            device = get_fpga(device_id)
            result = await asyncio.to_thread(self._actions.reset_board, device_state=device)

            # State may have changed while the tool was running.
            device = get_fpga(device_id)
            if not result.ok:
                device = add_fault(device, FaultType.PROGRAMMING_FAILED)
                logger.error("Reset failed on FPGA %s: %s, %s", device_id, result.error, result.stderr)
                raise RuntimeError(result.stderr or "Reset failed")

            device = clear_fault(device,FaultType.PROGRAMMING_FAILED)
            device = clear_fault(device, FaultType.COMMUNICATION_LOST)
            device = update_fpga(device, bitstream_id=None)
            logger.info("Reset completed on FPGA %s", device_id)
            return device

    def clear_device_fault(
        self,
        device_id: str,
        fault_type: FaultType,
    ) -> FPGAState:
        device = get_fpga(device_id)

        if fault_type == FaultType.OVER_TEMPERATURE:
            temperature = device.telemetry.temperature_c
            if temperature is None:
                raise RuntimeError("Cannot clear thermal fault without valid telemetry")
            if temperature >= self.config.over_temperature_recovery_c:
                raise RuntimeError(f"FPGA is still too hot: {temperature:.1f} C")

        return clear_fault(device, fault_type)

    async def _discovery_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.config.discovery_interval_seconds)

                result = await asyncio.to_thread(self._actions.discover_jtag_targets)
                if not result.ok:
                    logger.warning("FPGA discovery failed: %s", result.stderr or result.error)
                    continue

                targets = result.data or []
                new = register_jtag_discovery(targets)
                if new:
                    logger.debug("FPGA discovery completed: %d device(s) found", len(new))
        except asyncio.CancelledError:
            logger.debug("FPGA discovery task stopped")
            raise

    async def _telemetry_loop(self) -> None:
        try:
            while self._running:
                await self._read_all_telemetry()
                await asyncio.sleep(self.config.telemetry_interval_seconds)
        except asyncio.CancelledError:
            logger.debug("FPGA telemetry task stopped")
            raise

    async def _read_all_telemetry(self) -> None:
        devices = list_fpgas()

        for device in devices:
            result = await asyncio.to_thread(self._actions.read_telemetry, device_state=device)
            if not result.ok or result.data is None:
                logger.warning("FPGA telemetry failed: %s", result.stderr or result.error)

            await self._handle_telemetry_update(device, result)

    async def _handle_telemetry_update(self, device: FPGAState, result: ActionResult):
        if not result.ok:
            add_fault(device, FaultType.COMMUNICATION_LOST)
            return

        device = clear_fault(device, FaultType.COMMUNICATION_LOST)
        device = update_fpga(device, telemetry=result.data)
        self._evaluate_safety(device)

    def _evaluate_safety(
        self,
        device: FPGAState,
    ) -> None:
        temperature = device.telemetry.temperature_c
        if temperature is None or temperature >= self.config.over_temperature_c:
            self._safety_reset(device)
            add_fault(device, FaultType.OVER_TEMPERATURE)
        elif temperature < self.config.over_temperature_recovery_c:
            clear_fault(device, FaultType.OVER_TEMPERATURE)

    async def _safety_reset(
        self,
        device_id: str,
    ) -> None:
        lock = self._get_device_lock(device_id)
        async with lock:
            device = get_fpga(device_id)
            result = await asyncio.to_thread(self._actions.reset_board, device_state=device)
            if not result.ok:
                logger.critical("Safety reset failed on FPGA %s: %s, %s", device_id, result.error, result.stderr)
                return
            
            update_fpga(device, bitstream_id=None)

    def _get_device_lock(
        self,
        device_id: str,
    ) -> asyncio.Lock:
        if device_id not in self._device_locks:
            self._device_locks[device_id] = asyncio.Lock()

        return self._device_locks[device_id]

def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()