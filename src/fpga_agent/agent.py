import logging
from dataclasses import dataclass
import asyncio
import hashlib
import time
from pathlib import Path
from datetime import datetime

from .actions import BoardActions, ActionResult, ActionError
from .fpga import register_jtag_discovery, list_fpgas, update_fpga, add_fault, clear_fault, get_fpga, FPGAState, FPGATelemetry, FaultType

logger = logging.getLogger('agent')

@dataclass(frozen=True)
class AgentConfig:
    discovery_interval_seconds: float = 5.0
    telemetry_interval_seconds: float = 1.0

    over_temperature_c: float = 75.0
    over_temperature_recovery_c: float = 60.0
    reserved_for_projects: bool = False

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
        self._subscribers: dict[str, set[asyncio.Queue[FPGAState]]] = {}
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._last_telemetry_log: dict[str, tuple[float | None, float]] = {}

    async def start(self) -> None:
        if self._running:
            logger.debug("FPGA agent is already running")
            return
        logger.info("[bold blue]╭─ FPGA agent boot[/]")
        logger.info(
            "[blue]│ config[/] discovery=%.1fs telemetry=%.1fs thermal_limit=%.1f°C recovery=%.1f°C reserved_for_projects=%s",
            self.config.discovery_interval_seconds,
            self.config.telemetry_interval_seconds,
            self.config.over_temperature_c,
            self.config.over_temperature_recovery_c,
            self.config.reserved_for_projects,
        )

        logger.info("[blue]│[/] starting persistent [bold]XSDB[/] action session")
        actions_start = await asyncio.to_thread(self._actions.start)
        if not actions_start.ok:
            logger.error(
                "[bold red]╰─ boot failed[/] XSDB session: %s",
                actions_start.stderr or actions_start.error,
            )
            return
        logger.info("[green]│ ✓[/] XSDB session ready")

        logger.info("[blue]│[/] starting persistent [bold]Vivado hw_manager[/] telemetry session")
        telemetry_start = await asyncio.to_thread(self._actions.start_telemetry)
        if not telemetry_start.ok:
            logger.error(
                "[bold red]╰─ boot failed[/] Vivado session: %s",
                telemetry_start.stderr or telemetry_start.error,
            )
            await asyncio.to_thread(self._actions.stop)
            return
        logger.info("[green]│ ✓[/] Vivado telemetry session ready")

        logger.info("[blue]│[/] discovering JTAG target graph")
        result = await asyncio.to_thread(self._actions.discover_jtag_targets)
        if not result.ok:
            logger.error(
                "[bold red]╰─ boot failed[/] discovery: %s",
                result.stderr or result.error,
            )
            await asyncio.to_thread(self._actions.stop)
            return
        targets = result.data or []
        if not targets:
            logger.error("[bold red]╰─ boot failed[/] no FPGA devices discovered")
            await asyncio.to_thread(self._actions.stop)
            return
        devices = self._apply_reserved_for_projects(
            register_jtag_discovery(targets)
        )
        for device in devices:
            logger.info(
                "[green]│ ✓[/] device=%s fpga=%s processor=%s dap=%s",
                device.device_id,
                device.target_ctx.fpga_ctx,
                device.target_ctx.processor_ctx or "none",
                device.target_ctx.dap_ctx or "none",
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
        logger.info("[bold green]╰─ FPGA agent online[/] devices=%d monitoring=enabled", len(targets))

    async def stop(self) -> None:
        if not self._running:
            return
        logger.info("[bold yellow]╭─ FPGA agent shutdown[/]")
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
        await asyncio.to_thread(self._actions.stop)
        logger.info("[bold yellow]╰─ FPGA agent stopped[/]")

    async def subscribe(self, device_id: str):
        device = get_fpga(device_id)
        queue: asyncio.Queue[FPGAState] = asyncio.Queue(maxsize=1)
        self._subscribers.setdefault(device_id, set()).add(queue)

        try:
            yield device  # immediately send current state
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(device_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(device_id, None)

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
            logger.info("[blue]▶ pl.program[/] device=%s bitstream=%s", device_id, bitstream)
            result = await asyncio.to_thread(self._actions.program_pl, bitstream, device_state=device)

            # State may have changed while the tool was running.
            device = get_fpga(device_id)
            if not result.ok:
                device = add_fault(device, FaultType.PROGRAMMING_FAILED)
                logger.error("[bold red]✖ pl.program[/] device=%s error=%s detail=%s", device_id, result.error, result.stderr)
                raise RuntimeError(result.stderr or "PL programming failed")
            
            bitstream_id = _sha256_file(Path(bitstream).expanduser().resolve())
            device = clear_fault(device,FaultType.PROGRAMMING_FAILED)
            device = clear_fault(device, FaultType.COMMUNICATION_LOST)
            device = update_fpga(device, bitstream_id=bitstream_id)
            self._publish_state(device)
            logger.info("[green]✓ pl.program[/] device=%s bitstream=%s", device_id, bitstream_id[:12])
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
            logger.info("[blue]▶ ps.program[/] device=%s elf=%s", device_id, elf)
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
                logger.error("[bold red]✖ ps.program[/] device=%s error=%s detail=%s", device_id, result.error, result.stderr)
                raise RuntimeError(result.stderr or "PS programming failed")

            device = clear_fault(device,FaultType.PROGRAMMING_FAILED)
            device = clear_fault(device, FaultType.COMMUNICATION_LOST)
            self._publish_state(device)
            logger.info("[green]✓ ps.program[/] device=%s", device_id)
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
                logger.error("[bold red]✖ board.reset[/] device=%s error=%s detail=%s", device_id, result.error, result.stderr)
                raise RuntimeError(result.stderr or "Reset failed")

            device = clear_fault(device,FaultType.PROGRAMMING_FAILED)
            device = clear_fault(device, FaultType.COMMUNICATION_LOST)
            device = update_fpga(device, bitstream_id=None)
            self._publish_state(device)
            logger.info("[green]✓ board.reset[/] device=%s bitstream=cleared", device_id)
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

        device = clear_fault(device, fault_type)
        self._publish_state(device)
        return device

    def set_reserved_for_projects(
        self,
        device_id: str,
        reserved_for_projects: bool,
    ) -> FPGAState:
        device = get_fpga(device_id)
        device = update_fpga(
            device,
            reserved_for_projects=reserved_for_projects,
        )
        self._publish_state(device)
        logger.warning(
            "[bold red]◇ reservation[/] device=%s reserved_for_projects=%s",
            device_id,
            reserved_for_projects,
        )
        return device

    async def _discovery_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.config.discovery_interval_seconds)

                result = await asyncio.to_thread(self._actions.discover_jtag_targets)
                if not self._running:
                    return
                
                if not result.ok:
                    logger.warning("[yellow]◇ discovery[/] failed: %s", result.stderr or result.error)
                    continue

                targets = result.data or []
                new = self._apply_reserved_for_projects(
                    register_jtag_discovery(targets)
                )
                if new:
                    logger.info("[green]◇ discovery[/] new_devices=%d", len(new))
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
            if not self._running:
                return

            duration = (
                datetime.fromisoformat(result.finished_at)
                - datetime.fromisoformat(result.started_at)
            )
            logger.debug("telemetry sample device=%s duration=%.3fs", device.device_id, duration.total_seconds())
            await self._handle_telemetry_update(device, result)

    async def _handle_telemetry_update(self, device: FPGAState, result: ActionResult):
        if not result.ok:
            if _has_fault(device, FaultType.COMMUNICATION_LOST):
                logger.debug("telemetry still unavailable device=%s error=%s detail=%s", device.device_id, result.error, result.stderr)
                return
            logger.warning("[yellow]◇ telemetry[/] device=%s failed error=%s detail=%s fault=latched", device.device_id, result.error, result.stderr)
            add_fault(device, FaultType.COMMUNICATION_LOST)
            return

        device = clear_fault(device, FaultType.COMMUNICATION_LOST)
        device = update_fpga(device, telemetry=result.data)
        self._log_telemetry_sample(device, result.data)
        await self._evaluate_safety(device)

        device = get_fpga(device.device_id)
        self._publish_state(device)

    def _log_telemetry_sample(self, device: FPGAState, telemetry: FPGATelemetry) -> None:
        temperature = telemetry.temperature_c
        now = time.monotonic()
        previous_temperature, previous_log_at = self._last_telemetry_log.get(device.device_id, (None, 0.0))
        first_sample = previous_temperature is None
        changed = temperature is not None and previous_temperature is not None and abs(temperature - previous_temperature) >= 0.5
        heartbeat_due = now - previous_log_at >= 600.0
        near_limit = temperature is not None and temperature >= self.config.over_temperature_c - 5.0
        if not (first_sample or changed):
            return
        self._last_telemetry_log[device.device_id] = (temperature, now)
        style = "red" if near_limit else "cyan"
        logger.info(
            "[bold %s]◇ telemetry[/] device=%s temp=%s status=%s faults=%d",
            style,
            device.device_id,
            _format_temperature(temperature),
            device.status,
            len(device.faults),
        )

    def _publish_state(self, device: FPGAState) -> None:
        for queue in self._subscribers.get(device.device_id, set()).copy():
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(device)

    def _apply_reserved_for_projects(self, devices: list[FPGAState]) -> list[FPGAState]:
        if not self.config.reserved_for_projects:
            return devices
        return [
            update_fpga(device, reserved_for_projects=True)
            for device in devices
        ]

    async def _evaluate_safety(
        self,
        device: FPGAState,
    ) -> None:
        temperature = device.telemetry.temperature_c
        if temperature is None or temperature >= self.config.over_temperature_c:
            if _has_fault(device, FaultType.OVER_TEMPERATURE):
                return
            logger.critical(
                "[bold red]⚠ safety[/] device=%s temp=%s threshold=%.1f°C action=reset fault=latched",
                device.device_id,
                _format_temperature(temperature),
                self.config.over_temperature_c,
            )
            await self._safety_reset(device.device_id)
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


def _format_temperature(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f}°C"


def _has_fault(device: FPGAState, fault_type: FaultType) -> bool:
    return any(fault.type == fault_type for fault in device.faults)