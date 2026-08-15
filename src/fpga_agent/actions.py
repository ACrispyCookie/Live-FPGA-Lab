from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from enum import Enum

from .fpga import FPGATelemetry, FPGAState, JTAGTargetContext

logger = logging.getLogger('actions')

DEFAULT_VIVADO_SETTINGS = Path(os.environ.get("FPGA_AGENT_VIVADO_SETTINGS", "~/Xilinx/2025.2/Vivado/settings64.sh")).expanduser()
DEFAULT_XSDB = Path(os.environ.get("FPGA_AGENT_XSDB", "xsdb"))
DEFAULT_VIVADO = os.environ.get("FPGA_AGENT_VIVADO", "vivado")
TELEMETRY_MARKER = "FPGA_AGENT_TELEMETRY_JSON:"
TARGET_MARKER = "FPGA_AGENT_TARGET"

DISCOVER_JTAG_TARGETS_TCL = f"""
connect
proc is_fpga {{name}} {{
    return [regexp -nocase {{^(xc|xck|xcu|xq|xa)}} $name]
}}
proc is_processor {{name}} {{
    return [regexp -nocase {{(cortex|microblaze|risc-v|riscv)}} $name]
}}
set fpgas {{}}
set processors {{}}
set daps {{}}
foreach props [targets -target-properties] {{
    if {{![dict exists $props jtag_cable_serial] ||
         ![dict exists $props jtag_device_ctx] ||
         ![dict exists $props name] ||
         ![dict exists $props target_id]}} {{
        continue
    }}
    set cable_serial [dict get $props jtag_cable_serial]
    set device_ctx [dict get $props jtag_device_ctx]
    set name [dict get $props name]
    set target_id [dict get $props target_id]
    if {{[is_fpga $name]}} {{
        lappend fpgas [list $cable_serial $device_ctx $name]
    }}
    if {{[is_processor $name]}} {{
        dict lappend processors $cable_serial [list $device_ctx $name]
    }}
    if {{[dict exists $props jtag_device_name]}} {{
        set device_name [dict get $props jtag_device_name]
        if {{[string match -nocase "*dap*" $device_name]}} {{
            set level 0
            if {{[dict exists $props level]}} {{
                set level [dict get $props level]
            }}

            if {{$level == 0 || ![dict exists $daps $cable_serial]}} {{
                dict set daps $cable_serial $target_id
            }}
        }}
    }}
}}
foreach fpga $fpgas {{
    lassign $fpga cable_serial fpga_ctx fpga_name
    set processor_ctx ""
    set processor_name ""
    set dap_id ""
    if {{[dict exists $processors $cable_serial]}} {{
        set cores [dict get $processors $cable_serial]
        set selected [lindex $cores 0]

        foreach core $cores {{
            if {{[string match "*#0*" [lindex $core 1]]}} {{
                set selected $core
                break
            }}
        }}

        lassign $selected processor_ctx processor_name
    }}
    if {{[dict exists $daps $cable_serial]}} {{
        set dap_id [dict get $daps $cable_serial]
    }}
    puts "{TARGET_MARKER}\\t$cable_serial\\t$fpga_ctx\\t$fpga_name\\t$processor_ctx\\t$processor_name\\t$dap_id"
}}
exit
""".strip()

PROGRAM_PL_TCL = """
connect
targets -set @@FPGA_TARGET_ID@@
fpga -file @@BITSTREAM@@
puts {fpga-agent: programmed PL}
exit
""".strip()

PROGRAM_PS_TCL = """
connect
targets -set @@CORE_TARGET_ID@@
@@RESET_PROCESSOR@@
source @@PS7_INIT_TCL@@
ps7_init
ps7_post_config
dow @@ELF@@
@@CONTINUE_AFTER_DOWNLOAD@@
puts {fpga-agent: programmed PS}
exit
""".strip()

RESET_BOARD_TCL = """
connect
catch {
    targets -set @@CORE_TARGET_ID@@
    stop
    rst -processor
    stop
}
@@DAP_RESET_COMMAND@@
catch {
    targets -set @@FPGA_TARGET_ID@@
    rst -srst
}
catch {
    targets -set @@CORE_TARGET_ID@@
    set ctrl [mrd -value 0xF8007000]
    mwr 0xF8007000 [expr {$ctrl & ~(1 << 30)}]
    after 100
    mwr 0xF8007000 [expr {$ctrl | (1 << 30)}]
}
catch {
    targets -set @@FPGA_TARGET_ID@@
    puts [fpga -state]
}
puts {fpga-agent: reset complete}
exit
""".strip()

VIVADO_TELEMETRY_TCL = r"""
proc emit_telemetry {payload} {
    puts "FPGA_AGENT_TELEMETRY_JSON:$payload"
}

if {[catch {
    open_hw_manager
    connect_hw_server
    set targets [get_hw_targets *@@CABLE@@*]
    if {[llength $targets] == 0} { error "no hardware target found for cable @@CABLE@@" }
    current_hw_target [lindex $targets 0]
    open_hw_target
    set devices [get_hw_devices *@@FPGA_NAME@@*]
    if {[llength $devices] == 0} { error "no hardware device found for FPGA @@FPGA_NAME@@" }
    set device [lindex $devices 0]
    current_hw_device $device
    refresh_hw_device $device
    set temperature ""
    foreach prop {TEMPERATURE XADC_TEMPERATURE TEMP} {
        if {[catch {set value [get_property $prop $device]}] == 0 && $value ne ""} {
            set temperature $value
            break
        }
    }
    if {$temperature eq ""} { error "temperature property unavailable" }
    emit_telemetry "{\"temperature_c\": $temperature}"
} result]} {
    set escaped [string map {\\ \\\\ \" \\\" \n { }} $result]
    emit_telemetry "{\"error\": \"$escaped\"}"
}
exit
""".strip()


class ActionError(str, Enum):
    FILE_MISSING = "file_missing"
    TOOL_MISSING = "tool_missing"
    FPGA_INCOMPATIBLE = "fpga_incompatible"
    COMMAND_ERROR = "command_error"
    TIMEOUT = "timeout"

@dataclass(frozen=True)
class ActionResult:
    ok: bool
    error: ActionError | None
    command: tuple[str, ...]
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "command": list(self.command),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "data": self.data,
        }

class BoardActions:
    def __init__(
        self,
        *,
        vivado_settings: str | Path = DEFAULT_VIVADO_SETTINGS,
        xsdb: str | Path = DEFAULT_XSDB,
        vivado: str = DEFAULT_VIVADO,
        timeout_seconds: int = 180,
    ):
        self.vivado_settings = Path(vivado_settings).expanduser()
        self.xsdb = Path(xsdb)
        self.vivado = vivado
        self.timeout_seconds = timeout_seconds

    def discover_jtag_targets(self) -> ActionResult:
        result = self._run_xsdb(DISCOVER_JTAG_TARGETS_TCL, timeout_seconds=60)
        if not result.ok:
            return result
        contexts = parse_xsdb_targets(result.stdout)
        return _with_data(result, contexts)

    def program_pl(self, bitstream: str | Path, *, device_state: FPGAState) -> ActionResult:
        bitstream_path, error = _require_file(bitstream, label="PL bitstream")
        if error:
            return error
        script = _render_template(
            PROGRAM_PL_TCL,
            FPGA_TARGET_ID=device_state.target_ctx.fpga_id,
            BITSTREAM=_tcl_path(bitstream_path),
        )
        result = self._run_xsdb(script, timeout_seconds=self.timeout_seconds)
        return result

    def program_ps(
        self,
        *,
        device_state: FPGAState,
        ps7_init_tcl: str | Path,
        elf: str | Path,
        reset_processor: bool = True,
        continue_after_download: bool = True,
    ) -> ActionResult:
        if not device_state.target_ctx.core_id:
            return _local_error(ActionError.FPGA_INCOMPATIBLE, "PS programming requires a discovered core target id")
        ps7_init_path, error = _require_file(ps7_init_tcl, label="PS7 init Tcl")
        if error:
            return error
        elf_path, error = _require_file(elf, label="PS ELF")
        if error:
            return error
        script = _render_template(
            PROGRAM_PS_TCL,
            CORE_TARGET_ID=device_state.target_ctx.core_id,
            RESET_PROCESSOR="rst -processor" if reset_processor else "",
            PS7_INIT_TCL=_tcl_path(ps7_init_path),
            ELF=_tcl_path(elf_path),
            CONTINUE_AFTER_DOWNLOAD="con" if continue_after_download else "",
        )
        return self._run_xsdb(script, timeout_seconds=self.timeout_seconds)

    def reset_board(self, *, device_state: FPGAState) -> ActionResult:
        if not device_state.target_ctx.core_id:
            return _local_error(ActionError.FPGA_INCOMPATIBLE, "board reset requires a discovered core target id")
        script = _render_template(
            RESET_BOARD_TCL,
            CORE_TARGET_ID=device_state.target_ctx.core_id,
            DAP_RESET_COMMAND=_dap_reset_command(device_state.target_ctx),
            FPGA_TARGET_ID=device_state.target_ctx.fpga_id,
        )
        result = self._run_xsdb(script, timeout_seconds=90)
        return result

    def read_telemetry(self, *, device_state: FPGAState) -> ActionResult:
        logging.info("reading" + VIVADO_TELEMETRY_TCL)
        script = _render_template(
            VIVADO_TELEMETRY_TCL,
            CABLE=device_state.target_ctx.cable,
            FPGA_NAME=device_state.target_ctx.fpga_name,
        )
        logging.info("script: ")
        result = self._run_vivado(script, timeout_seconds=90)
        logging.info(result.stdout)
        payload = parse_telemetry_payload(result.stdout) or {}
        telemetry = _telemetry_from_payload(payload)
        if not telemetry:
            return ActionResult(
                ok=False,
                error=ActionError.COMMAND_ERROR,
                command=result.command,
                stdout=result.stdout,
                stderr=result.stderr,
                started_at=result.started_at,
                finished_at=result.finished_at,
            )
        return _with_data(result, telemetry)

    def _run_xsdb(self, script: str, *, timeout_seconds: int) -> ActionResult:
        return _run_xilinx_script(
            executable=str(self.xsdb),
            script=script,
            vivado_settings=self.vivado_settings,
            timeout_seconds=timeout_seconds,
        )

    def _run_vivado(self, script: str, *, timeout_seconds: int) -> ActionResult:
        return _run_xilinx_script(
            executable=self.vivado,
            executable_args=("-mode", "batch", "-source"),
            script=script,
            vivado_settings=self.vivado_settings,
            timeout_seconds=timeout_seconds,
        )

def parse_xsdb_targets(stdout: str) -> list[JTAGTargetContext]:
    contexts = []
    for line in stdout.splitlines():
        if not line.startswith(f"{TARGET_MARKER}\t"):
            continue
        parts = line.split("\t", 6)
        if len(parts) != 7:
            continue

        _, cable_serial, fpga_ctx, fpga_name, processor_ctx, processor_name, dap_id = parts
        contexts.append(
            JTAGTargetContext(
                cable_serial=cable_serial,
                fpga_ctx=fpga_ctx,
                fpga_name=fpga_name,
                processor_ctx=processor_ctx or None,
                processor_name=processor_name or None,
                dap_id=dap_id or None,
            )
        )

    return contexts

def parse_telemetry_payload(stdout: str) -> dict[str, Any] | None:
    """Parse the telemetry JSON emitted by the Tcl probe."""

    for line in stdout.splitlines():
        if TELEMETRY_MARKER not in line:
            continue
        payload = line.split(TELEMETRY_MARKER, 1)[1].strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {"error": f"invalid JSON payload: {payload}"}
        return parsed if isinstance(parsed, dict) else {"error": "telemetry payload was not an object"}
    return None

def _run_xilinx_script(
    *,
    executable: str,
    script: str,
    vivado_settings: Path,
    timeout_seconds: int,
    executable_args: tuple[str, ...] = (),
) -> ActionResult:
    vivado_settings = Path(vivado_settings).expanduser()
    if not vivado_settings.exists():
        return _local_error(ActionError.TOOL_MISSING, f"Vivado settings file not found: {vivado_settings}")
    script_path = _write_temp_script(script)
    command = ("bash", "-lc", _shell_command(vivado_settings, executable, executable_args, script_path))
    logging.info(command)
    started_at = datetime.now(UTC).isoformat()
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        finished_at = datetime.now(UTC).isoformat()
        stdout = _coerce_process_text(exc.stdout)
        stderr = _coerce_process_text(exc.stderr)
        return ActionResult(False, ActionError.TIMEOUT, command, stdout, stderr, started_at, finished_at)
    finally:
        script_path.unlink(missing_ok=True)
    finished_at = datetime.now(UTC).isoformat()
    error = None if completed.returncode == 0 else ActionError.COMMAND_ERROR
    return ActionResult(
        ok=completed.returncode == 0,
        error=error,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        started_at=started_at,
        finished_at=finished_at,
    )

def _local_error(error: ActionError, message: str) -> ActionResult:
    now = datetime.now(UTC).isoformat()
    return ActionResult(False, error, (), "", message, now, now)

def _with_data(result: ActionResult, data: Any) -> ActionResult:
    return ActionResult(result.ok, result.error, result.command, result.stdout, result.stderr, result.started_at, result.finished_at, data)

def _require_file(path: str | Path, *, label: str) -> tuple[Path | None, ActionResult | None]:
    result = Path(path).expanduser().resolve()
    if not result.is_file():
        return None, _local_error(ActionError.FILE_MISSING, f"{label} does not exist or is not a file: {result}")
    return result, None

def _write_temp_script(script: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".tcl", prefix="fpga-agent-", delete=False, encoding="utf-8")
    try:
        handle.write(script + "\n")
        return Path(handle.name)
    finally:
        handle.close()

def _shell_command(vivado_settings: Path, executable: str, executable_args: tuple[str, ...], script_path: Path) -> str:
    prefix = f"source {_sh_quote(str(vivado_settings))} >/dev/null 2>&1"
    args = " ".join(_sh_quote(arg) for arg in (*executable_args, str(script_path))) if executable_args else _sh_quote(str(script_path))
    return f"{prefix} && {_sh_quote(executable)} {args}"

def _render_template(template: str, **values: str) -> str:
    logging.info("calling\n")
    rendered = template
    logging.info(template)
    for key, value in values.items():
        rendered = rendered.replace("@@" + key + "@@", value)
    logging.info(rendered)
    return rendered

def _telemetry_from_payload(payload: dict[str, Any]) -> FPGATelemetry | None:
    temperature = payload.get("temperature_c")
    if not isinstance(temperature, int | float):
        return None
    return FPGATelemetry(temperature_c=float(temperature), checked_at=datetime.now(UTC))

def _dap_reset_command(target_ctx: JTAGTargetContext) -> str:
    if not target_ctx.dap_id:
        return ""
    return f"""catch {{
    targets -set {target_ctx.dap_id}
    rst -dap
}}"""

def _tcl_path(path: Path) -> str:
    return str(path).replace("\\", "/")

def _coerce_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value

def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
