import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest

from fpga_agent.actions import (
    ActionError,
    ActionResult,
    BoardActions,
    COMMAND_DONE_MARKER,
    TclSession,
)
from fpga_agent.agent import Agent, AgentConfig
from fpga_agent.fpga import (
    _FPGA_LOCK,
    _FPGA_STATES,
    FPGATelemetry,
    FPGAStatus,
    FaultType,
    JTAGTargetContext,
    get_fpga,
    register_jtag_discovery,
    update_fpga,
)


@pytest.fixture(autouse=True)
def clear_fpga_state():
    with _FPGA_LOCK:
        _FPGA_STATES.clear()
    yield
    with _FPGA_LOCK:
        _FPGA_STATES.clear()


def _target(serial: str = "210299730789") -> JTAGTargetContext:
    return JTAGTargetContext(
        cable_serial=serial,
        fpga_ctx="jsn-JTAG-SMT3-210299730789-12790793-0",
        fpga_name="xc7z020_1",
        processor_ctx="jsn-JTAG-SMT3-210299730789-12790793-0-1",
        processor_name="Cortex-A9 MPCore #0",
        dap_ctx="jsn-JTAG-SMT3-210299730789-12790793-0-DAP",
    )


def test_discovery_marks_known_missing_board_offline_and_publishes_update():
    async def run():
        agent = Agent(AgentConfig())
        device = register_jtag_discovery([_target()])[0]
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        agent._subscribers[device.device_id] = {queue}

        await agent._handle_discovery_result([])

        updated = get_fpga(device.device_id)
        assert updated.status == FPGAStatus.OFFLINE
        assert [fault.type for fault in updated.faults] == [FaultType.COMMUNICATION_LOST]
        assert queue.get_nowait().status == FPGAStatus.OFFLINE

    asyncio.run(run())


def test_discovery_failure_marks_known_board_offline_and_publishes_update():
    async def run():
        agent = Agent(AgentConfig())
        device = register_jtag_discovery([_target()])[0]
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        agent._subscribers[device.device_id] = {queue}

        await agent._handle_discovery_failure(
            ActionResult(
                ok=False,
                error=ActionError.COMMAND_ERROR,
                command=("xsdb",),
                stdout="",
                stderr="hardware target disappeared",
                started_at="2026-01-01T00:00:00+00:00",
                finished_at="2026-01-01T00:00:01+00:00",
            )
        )

        updated = get_fpga(device.device_id)
        assert updated.status == FPGAStatus.OFFLINE
        assert queue.get_nowait().status == FPGAStatus.OFFLINE

    asyncio.run(run())


def test_discovery_clears_offline_fault_when_board_reappears():
    async def run():
        agent = Agent(AgentConfig())
        device = register_jtag_discovery([_target()])[0]

        await agent._handle_discovery_result([])
        assert get_fpga(device.device_id).status == FPGAStatus.OFFLINE

        await agent._handle_discovery_result([_target()])

        updated = get_fpga(device.device_id)
        assert updated.status == FPGAStatus.IDLE
        assert not [fault for fault in updated.faults if fault.type == FaultType.COMMUNICATION_LOST]

    asyncio.run(run())


def test_reconnected_board_does_not_keep_stale_running_bitstream():
    async def run():
        agent = Agent(AgentConfig())
        device = register_jtag_discovery([_target()])[0]
        update_fpga(device, bitstream_id="stale-bitstream")
        assert get_fpga(device.device_id).status == FPGAStatus.RUNNING

        await agent._handle_discovery_result([])
        assert get_fpga(device.device_id).status == FPGAStatus.OFFLINE

        await agent._handle_discovery_result([_target()])

        updated = get_fpga(device.device_id)
        assert updated.status == FPGAStatus.IDLE
        assert updated.bitstream_id is None

    asyncio.run(run())


def test_implausible_telemetry_marks_communication_lost_not_over_temperature():
    async def run():
        agent = Agent(AgentConfig())
        device = register_jtag_discovery([_target()])[0]
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        agent._subscribers[device.device_id] = {queue}

        await agent._handle_telemetry_update(
            device,
            ActionResult(
                ok=True,
                error=None,
                command=("vivado",),
                stdout="",
                stderr="",
                started_at="2026-01-01T00:00:00+00:00",
                finished_at="2026-01-01T00:00:01+00:00",
                data=FPGATelemetry(temperature_c=270.0),
            ),
        )

        updated = get_fpga(device.device_id)
        assert updated.status == FPGAStatus.OFFLINE
        assert [fault.type for fault in updated.faults] == [FaultType.COMMUNICATION_LOST]
        assert queue.get_nowait().status == FPGAStatus.OFFLINE

    asyncio.run(run())


def test_discovery_command_can_return_zero_targets_without_timeout_marker():
    actions = BoardActions.__new__(BoardActions)
    seen = {}

    def fake_run_xsdb(script: str, *, timeout_seconds: int, marker: str = COMMAND_DONE_MARKER):
        seen["marker"] = marker
        return ActionResult(
            ok=True,
            error=None,
            command=("xsdb",),
            stdout=f"{COMMAND_DONE_MARKER}\tok\t\n",
            stderr="",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:00+00:00",
        )

    actions.timeout_seconds = 1
    actions._run_xsdb = fake_run_xsdb

    result = actions.discover_jtag_targets()

    assert result.ok
    assert result.data == []
    assert seen["marker"] == COMMAND_DONE_MARKER


def test_tcl_read_until_times_out_on_partial_line_without_freezing():
    process = subprocess.Popen(
        ["python", "-c", "import sys, time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(5)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    session = TclSession.__new__(TclSession)
    session._process = process

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(session._read_until, "NEVER", timeout_seconds=0.1)
        try:
            ok, stdout, error = future.result(timeout=0.5)
        except TimeoutError:
            process.kill()
            raise AssertionError("_read_until blocked on a partial line")
        finally:
            process.kill()
            process.wait(timeout=2)

    assert not ok
    assert stdout == "partial"
    assert "timed out" in error
