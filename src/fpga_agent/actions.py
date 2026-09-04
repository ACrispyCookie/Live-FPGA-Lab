from __future__ import annotations

import json
import logging
import os
import re
import signal
import select
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .fpga import FPGATelemetry, FPGAState, JTAGTargetContext

logger = logging.getLogger("actions")

DEFAULT_VIVADO_SETTINGS = Path(os.environ.get("FPGA_AGENT_VIVADO_SETTINGS", "~/Xilinx/2025.2/Vivado/settings64.sh")).expanduser()
DEFAULT_XSDB = Path(os.environ.get("FPGA_AGENT_XSDB", "xsdb"))
DEFAULT_VIVADO = os.environ.get("FPGA_AGENT_VIVADO", "vivado")
DEFAULT_TOOL_TIMEOUT_SECONDS = int(os.environ.get("FPGA_AGENT_TOOL_TIMEOUT_SECONDS", "120"))
TELEMETRY_MARKER = "FPGA_AGENT_TELEMETRY_JSON:"
TARGET_MARKER = "FPGA_AGENT_TARGET"
COMMAND_DONE_MARKER = "FPGA_AGENT_COMMAND_DONE"
XSDB_READY_MARKER = "FPGA_AGENT_XSDB_READY"
VIVADO_READY_MARKER = "FPGA_AGENT_VIVADO_READY"
SCRIPT_END_MARKER = "__FPGA_AGENT_SCRIPT_END__"

XSDB_SESSION_TCL = f"""
proc fpga_agent_escape {{value}} {{
    return [string map {{\\ \\\\ \t {{ }} \r {{ }} \n {{ }}}} $value]
}}
connect
puts {{{XSDB_READY_MARKER}}}
flush stdout
while {{[gets stdin line] >= 0}} {{
    if {{$line eq "quit"}} {{ exit }}
    set script ""
    while {{$line ne "{SCRIPT_END_MARKER}"}} {{
        append script $line "\n"
        if {{[gets stdin line] < 0}} {{ exit }}
    }}
    if {{[catch {{uplevel #0 $script}} result]}} {{
        puts "{COMMAND_DONE_MARKER}\terror\t[fpga_agent_escape $result]"
    }} else {{
        puts "{COMMAND_DONE_MARKER}\tok\t[fpga_agent_escape $result]"
    }}
    flush stdout
}}
""".strip()

VIVADO_SESSION_TCL = f"""
proc fpga_agent_escape {{value}} {{
    return [string map {{\\ \\\\ \t {{ }} \r {{ }} \n {{ }}}} $value]
}}
if {{[catch {{
    open_hw_manager
    connect_hw_server
}} result]}} {{
    puts "{COMMAND_DONE_MARKER}\terror\t[fpga_agent_escape $result]"
    flush stdout
    exit 1
}}
puts {{{VIVADO_READY_MARKER}}}
flush stdout
while {{[gets stdin line] >= 0}} {{
    if {{$line eq "quit"}} {{ exit }}
    set script ""
    while {{$line ne "{SCRIPT_END_MARKER}"}} {{
        append script $line "\n"
        if {{[gets stdin line] < 0}} {{ exit }}
    }}
    if {{[catch {{uplevel #0 $script}} result]}} {{
        puts "{COMMAND_DONE_MARKER}\terror\t[fpga_agent_escape $result]"
    }} else {{
        puts "{COMMAND_DONE_MARKER}\tok\t[fpga_agent_escape $result]"
    }}
    flush stdout
}}
""".strip()

DISCOVER_JTAG_TARGETS_TCL = f"""
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
         ![dict exists $props target_ctx] ||
         ![dict exists $props name]}} {{
        continue
    }}
    set cable_serial [dict get $props jtag_cable_serial]
    set target_ctx [dict get $props target_ctx]
    set name [dict get $props name]
    if {{[is_fpga $name]}} {{
        lappend fpgas [list $cable_serial $target_ctx $name]
    }}
    if {{[is_processor $name]}} {{
        dict lappend processors $cable_serial [list $target_ctx $name]
    }}
    if {{[dict exists $props jtag_device_name]}} {{
        set device_name [dict get $props jtag_device_name]
        if {{[string match -nocase "*dap*" $device_name]}} {{
            set level 0
            if {{[dict exists $props level]}} {{
                set level [dict get $props level]
            }}

            if {{$level == 0 || ![dict exists $daps $cable_serial]}} {{
                dict set daps $cable_serial $target_ctx
            }}
        }}
    }}
}}
foreach fpga $fpgas {{
    lassign $fpga cable_serial fpga_ctx fpga_name
    set processor_ctx ""
    set processor_name ""
    set dap_ctx ""
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
        set dap_ctx [dict get $daps $cable_serial]
    }}
    puts "{TARGET_MARKER}\\t$cable_serial\\t$fpga_ctx\\t$fpga_name\\t$processor_ctx\\t$processor_name\\t$dap_ctx"
}}
""".strip()

PROGRAM_PL_TCL = """
targets -set -filter {target_ctx == "@@FPGA_CTX@@"}
fpga -file @@BITSTREAM@@
puts {fpga-agent: programmed PL}
""".strip()

PROGRAM_PS_TCL = """
targets -set -filter {target_ctx == "@@PROCESSOR_CTX@@"}
@@RESET_PROCESSOR@@
source @@PS7_INIT_TCL@@
ps7_init
ps7_post_config
dow @@ELF@@
@@CONTINUE_AFTER_DOWNLOAD@@
puts {fpga-agent: programmed PS}
""".strip()

RESET_BOARD_TCL = """
targets -set -filter {target_ctx == "@@PROCESSOR_CTX@@"}
rst -system
after 500
puts {fpga-agent: reset complete}
""".strip()

TELEMETRY_TCL = r"""
proc emit_telemetry {payload} {
    puts "FPGA_AGENT_TELEMETRY_JSON:$payload"
    flush stdout
}
proc fpga_agent_json_escape {value} {
    return [string map {\ \\ " \" \n { }} $value]
}
if {[catch {
    set targets [get_hw_targets -quiet *@@CABLE@@*]
    if {[llength $targets] == 0} {
        error "no hardware target found for cable @@CABLE@@"
    }
    current_hw_target [lindex $targets 0]
    if {[catch {open_hw_target} open_result] && ![string match -nocase "*already*open*" $open_result]} {
        error $open_result
    }
    set devices [get_hw_devices -quiet *@@FPGA_NAME@@*]
    if {[llength $devices] == 0} {
        error "no hardware device found for FPGA @@FPGA_NAME@@"
    }
    set device [lindex $devices 0]
    current_hw_device $device
    refresh_hw_device $device
    set sysmons [get_hw_sysmons -quiet -of_objects $device]
    if {[llength $sysmons] == 0} {
        error "no system monitor found for FPGA @@FPGA_NAME@@"
    }
    set sysmon [lindex $sysmons 0]
    refresh_hw_sysmon -properties {TEMPERATURE} $sysmon
    set temperature [get_property TEMPERATURE $sysmon]
    if {$temperature eq ""} {
        error "temperature unavailable"
    }
    emit_telemetry "{\"temperature_c\": $temperature}"
} result]} {
    emit_telemetry "{\"error\": \"[fpga_agent_json_escape $result]\"}"
}
""".strip()


class ActionError(str, Enum):
    FILE_MISSING = "file_missing"
    TOOL_MISSING = "tool_missing"
    FPGA_INCOMPATIBLE = "fpga_incompatible"
    COMMAND_ERROR = "command_error"
    TIMEOUT = "timeout"
    NOT_STARTED = "not_started"


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


class TclSession:
    def __init__(
        self,
        *,
        name: str,
        executable: str,
        executable_args: tuple[str, ...],
        startup_script: str,
        ready_marker: str,
        vivado_settings: Path,
        timeout_seconds: int,
        cleanup_patterns: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.executable = executable
        self.executable_args = executable_args
        self.startup_script = startup_script
        self.ready_marker = ready_marker
        self.vivado_settings = Path(vivado_settings).expanduser()
        self.timeout_seconds = timeout_seconds
        self.cleanup_patterns = cleanup_patterns
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._script_path: Path | None = None
        self._command: tuple[str, ...] = ()

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self) -> ActionResult:
        with self._lock:
            if self.running:
                now = datetime.now(UTC).isoformat()
                return ActionResult(True, None, self._command, "", "", now, now)
            if not self.vivado_settings.exists():
                return _local_error(ActionError.TOOL_MISSING, f"Vivado settings file not found: {self.vivado_settings}")
            self._script_path = _write_temp_script(self.startup_script)
            self._command = (
                "bash",
                "-lc",
                _shell_command(self.vivado_settings, self.executable, self.executable_args, self._script_path),
            )
            started_at = datetime.now(UTC).isoformat()
            self._process = subprocess.Popen(
                self._command,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                start_new_session=True,
            )
            ok, stdout, error = self._read_until(self.ready_marker, timeout_seconds=self.timeout_seconds)
            finished_at = datetime.now(UTC).isoformat()
            if ok:
                return ActionResult(True, None, self._command, stdout, "", started_at, finished_at)
            stderr = self._read_stderr()
            self.stop()
            return ActionResult(False, ActionError.COMMAND_ERROR, self._command, stdout, stderr or error, started_at, finished_at)

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is not None:
                try:
                    if process.stdin and process.poll() is None:
                        process.stdin.write("quit\n")
                        process.stdin.flush()
                        process.stdin.close()
                except Exception:
                    pass
                try:
                    process.wait(timeout=2)
                except Exception:
                    self._terminate_process_group(process, signal.SIGTERM)
                    try:
                        process.wait(timeout=2)
                    except Exception:
                        self._terminate_process_group(process, signal.SIGKILL)
                        with suppress(Exception):
                            process.wait(timeout=2)
            if self._script_path is not None:
                self._script_path.unlink(missing_ok=True)
                self._script_path = None
            self._cleanup_detached_helpers()

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[str], sig: signal.Signals) -> None:
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        except Exception:
            try:
                if sig == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()
            except Exception:
                pass

    def _cleanup_detached_helpers(self) -> None:
        if not self.cleanup_patterns:
            return

        current_pid = os.getpid()
        for proc_dir in Path("/proc").glob("[0-9]*"):
            try:
                pid = int(proc_dir.name)
            except ValueError:
                continue
            if pid == current_pid:
                continue

            try:
                cmdline = (proc_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            except Exception:
                continue

            if not cmdline or not any(pattern in cmdline for pattern in self.cleanup_patterns):
                continue

            logger.warning("cleaning up detached %s helper pid=%s cmd=%s", self.name, pid, cmdline[:160])
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)

        time_limit = datetime.now(UTC).timestamp() + 2.0
        while datetime.now(UTC).timestamp() < time_limit:
            if not self._matching_helper_pids():
                return
            time.sleep(0.05)

        for pid in self._matching_helper_pids():
            logger.warning("force killing detached %s helper pid=%s", self.name, pid)
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)

    def _matching_helper_pids(self) -> list[int]:
        matches: list[int] = []
        current_pid = os.getpid()
        for proc_dir in Path("/proc").glob("[0-9]*"):
            try:
                pid = int(proc_dir.name)
            except ValueError:
                continue
            if pid == current_pid:
                continue
            try:
                cmdline = (proc_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            except Exception:
                continue
            if cmdline and any(pattern in cmdline for pattern in self.cleanup_patterns):
                matches.append(pid)
        return matches

    def run(self, script: str, *, timeout_seconds: float | None = None, marker: str = COMMAND_DONE_MARKER) -> ActionResult:
        with self._lock:
            if not self.running:
                started = self.start()
                if not started.ok:
                    return started
            process = self._process
            if process is None or process.stdin is None:
                return _local_error(ActionError.NOT_STARTED, f"{self.name} session is not running")
            started_at = datetime.now(UTC).isoformat()
            try:
                process.stdin.write(script.rstrip() + "\n")
                process.stdin.write(SCRIPT_END_MARKER + "\n")
                process.stdin.flush()
            except BrokenPipeError:
                self.stop()
                return ActionResult(False, ActionError.COMMAND_ERROR, self._command, "", f"{self.name} session exited", started_at, datetime.now(UTC).isoformat())
            ok, stdout, error = self._read_until(marker, timeout_seconds=timeout_seconds or self.timeout_seconds)
            finished_at = datetime.now(UTC).isoformat()
            if not ok:
                stderr = self._read_stderr()
                self.stop()
                return ActionResult(False, ActionError.COMMAND_ERROR, self._command, stdout, stderr or error, started_at, finished_at)
            command_error = _command_done_error(stdout)
            if command_error:
                return ActionResult(False, ActionError.COMMAND_ERROR, self._command, stdout, command_error, started_at, finished_at)
            return ActionResult(True, None, self._command, stdout, "", started_at, finished_at)

    def _read_until(self, marker: str, *, timeout_seconds: float) -> tuple[bool, str, str]:
        process = self._process
        if process is None or process.stdout is None:
            return False, "", "process is not running"
        deadline = datetime.now(UTC).timestamp() + timeout_seconds
        chunks: list[str] = []
        buffered = ""
        while datetime.now(UTC).timestamp() < deadline:
            remaining = max(0.0, deadline - datetime.now(UTC).timestamp())
            ready, _, _ = select.select([process.stdout], [], [], min(0.25, remaining))
            if ready:
                data = os.read(process.stdout.fileno(), 4096)
                if data:
                    text = data.decode(errors="replace")
                    chunks.append(text)
                    buffered += text
                    for line in buffered.splitlines():
                        if line.strip().startswith(marker):
                            return True, "".join(chunks), ""
            if process.poll() is not None:
                return False, "".join(chunks), f"process exited with {process.returncode}"
        return False, "".join(chunks), f"timed out waiting for {marker}"

    def _read_stderr(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        if process.poll() is None:
            ready, _, _ = select.select([process.stderr], [], [], 0)
            if not ready:
                return ""
        try:
            chunks: list[str] = []
            while True:
                ready, _, _ = select.select([process.stderr], [], [], 0)
                if not ready:
                    break
                data = os.read(process.stderr.fileno(), 4096)
                if not data:
                    break
                chunks.append(data.decode(errors="replace"))
            return "".join(chunks)
        except Exception:
            return ""


class BoardActions:
    def __init__(
        self,
        *,
        vivado_settings: str | Path = DEFAULT_VIVADO_SETTINGS,
        xsdb: str | Path = DEFAULT_XSDB,
        vivado: str = DEFAULT_VIVADO,
        timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
    ):
        self.vivado_settings = Path(vivado_settings).expanduser()
        self.xsdb = Path(xsdb)
        self.vivado = vivado
        self.timeout_seconds = timeout_seconds
        self._xsdb_session = TclSession(
            name="xsdb",
            executable=str(self.xsdb),
            executable_args=(),
            startup_script=XSDB_SESSION_TCL,
            ready_marker=XSDB_READY_MARKER,
            vivado_settings=self.vivado_settings,
            timeout_seconds=self.timeout_seconds,
        )
        self._vivado_session = TclSession(
            name="vivado",
            executable=self.vivado,
            executable_args=("-mode", "batch", "-source"),
            startup_script=VIVADO_SESSION_TCL,
            ready_marker=VIVADO_READY_MARKER,
            vivado_settings=self.vivado_settings,
            timeout_seconds=self.timeout_seconds,
            cleanup_patterns=("/cs_server", "xsdb-server.tcl"),
        )

    def start(self) -> ActionResult:
        return self._xsdb_session.start()

    def start_telemetry(self) -> ActionResult:
        return self._vivado_session.start()

    def stop(self) -> None:
        self._vivado_session.stop()
        self._xsdb_session.stop()

    def discover_jtag_targets(self, *, timeout_seconds: float | None = None) -> ActionResult:
        result = self._run_xsdb(DISCOVER_JTAG_TARGETS_TCL, timeout_seconds=timeout_seconds or self.timeout_seconds)
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
            FPGA_CTX=device_state.target_ctx.fpga_ctx,
            BITSTREAM=_tcl_path(bitstream_path),
        )
        return self._run_xsdb(script, timeout_seconds=self.timeout_seconds, marker="fpga-agent: programmed PL")

    def program_ps(
        self,
        *,
        device_state: FPGAState,
        ps7_init_tcl: str | Path,
        elf: str | Path,
        reset_processor: bool = True,
        continue_after_download: bool = True,
    ) -> ActionResult:
        if not device_state.target_ctx.processor_ctx:
            return _local_error(ActionError.FPGA_INCOMPATIBLE, "PS programming requires a discovered core target id")
        ps7_init_path, error = _require_file(ps7_init_tcl, label="PS7 init Tcl")
        if error:
            return error
        elf_path, error = _require_file(elf, label="PS ELF")
        if error:
            return error
        script = _render_template(
            PROGRAM_PS_TCL,
            PROCESSOR_CTX=device_state.target_ctx.processor_ctx,
            RESET_PROCESSOR="rst -processor" if reset_processor else "",
            PS7_INIT_TCL=_tcl_path(ps7_init_path),
            ELF=_tcl_path(elf_path),
            CONTINUE_AFTER_DOWNLOAD="con" if continue_after_download else "",
        )
        return self._run_xsdb(script, timeout_seconds=self.timeout_seconds, marker="fpga-agent: programmed PS")

    def reset_board(self, *, device_state: FPGAState) -> ActionResult:
        if not device_state.target_ctx.processor_ctx:
            return _local_error(ActionError.FPGA_INCOMPATIBLE, "board reset requires a discovered core target id")
        script = _render_template(
            RESET_BOARD_TCL,
            PROCESSOR_CTX=device_state.target_ctx.processor_ctx,
            FPGA_CTX=device_state.target_ctx.fpga_ctx,
            DAP_RESET_COMMAND=_dap_reset_command(device_state.target_ctx),
        )
        return self._run_xsdb(script, timeout_seconds=self.timeout_seconds, marker="fpga-agent: reset complete")

    def read_telemetry(self, *, device_state: FPGAState, timeout_seconds: float | None = None) -> ActionResult:
        script = _render_template(
            TELEMETRY_TCL,
            CABLE=device_state.target_ctx.cable_serial,
            FPGA_NAME=device_state.target_ctx.fpga_name,
        )
        result = self._run_vivado(script, timeout_seconds=timeout_seconds or self.timeout_seconds)
        if not result.ok:
            return result
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

    def _run_xsdb(self, script: str, *, timeout_seconds: float, marker: str = COMMAND_DONE_MARKER) -> ActionResult:
        return self._xsdb_session.run(script, timeout_seconds=timeout_seconds, marker=marker)

    def _run_vivado(self, script: str, *, timeout_seconds: float) -> ActionResult:
        return self._vivado_session.run(script, timeout_seconds=timeout_seconds, marker=TELEMETRY_MARKER)

def parse_xsdb_targets(stdout: str) -> list[JTAGTargetContext]:
    contexts = []
    for line in stdout.splitlines():
        if not line.startswith(f"{TARGET_MARKER}\t"):
            continue
        parts = line.split("\t", 6)
        if len(parts) != 7:
            continue
        _, cable_serial, fpga_ctx, fpga_name, processor_ctx, processor_name, dap_ctx = parts
        contexts.append(
            JTAGTargetContext(
                cable_serial=cable_serial,
                fpga_ctx=fpga_ctx,
                fpga_name=fpga_name,
                processor_ctx=processor_ctx or None,
                processor_name=processor_name or None,
                dap_ctx=dap_ctx or None,
            )
        )
    return contexts

def parse_telemetry_payload(stdout: str) -> dict[str, Any] | None:
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
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("@@" + key + "@@", value)
    return rendered

def _telemetry_from_payload(payload: dict[str, Any]) -> FPGATelemetry | None:
    temperature = payload.get("temperature_c")
    if not isinstance(temperature, int | float):
        return None
    return FPGATelemetry(temperature_c=float(temperature), checked_at=datetime.now(UTC))

def _dap_reset_command(target_ctx: JTAGTargetContext) -> str:
    if not target_ctx.dap_ctx:
        return ""

    return f"""fpga_agent_reset_step dap {{
    targets -set -filter {{target_ctx == \"{target_ctx.dap_ctx}\"}}
    rst -dap
}}"""

def _tcl_path(path: Path) -> str:
    return str(path).replace("\\", "/")

def _command_done_error(stdout: str) -> str | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(f"{COMMAND_DONE_MARKER}\terror\t"):
            return line.split("\t", 2)[2]
        if line.startswith(f"{COMMAND_DONE_MARKER}\tok"):
            return None
    return None

def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
