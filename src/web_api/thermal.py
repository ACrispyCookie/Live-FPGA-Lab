from __future__ import annotations

import json
import os
import select
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MAX_TEMPERATURE_C = float(os.environ.get("FPGA_DEMO_MAX_TEMPERATURE_C", "75.0"))
DEFAULT_VIVADO_SETTINGS = Path(os.environ.get("FPGA_DEMO_VIVADO_SETTINGS", "/home/njason/Xilinx/2025.2/Vivado/settings64.sh"))
DEFAULT_XSDB = Path(os.environ.get("FPGA_DEMO_XSDB", "xsdb"))
DEFAULT_CACHE_SECONDS = float(os.environ.get("FPGA_DEMO_TEMPERATURE_CACHE_SECONDS", "10"))
DEFAULT_READER_TIMEOUT_SECONDS = float(os.environ.get("FPGA_DEMO_TEMPERATURE_READ_TIMEOUT_SECONDS", "20"))


@dataclass(frozen=True)
class ThermalStatus:
    available: bool
    temperature_c: float | None
    max_temperature_c: float
    reason: str | None
    checked_at: str

    def to_dict(self) -> dict[str, float | str | bool | None]:
        return {
            "available": self.available,
            "temperature_c": self.temperature_c,
            "max_temperature_c": self.max_temperature_c,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


class ThermalGuard:
    def __init__(
        self,
        *,
        max_temperature_c: float = DEFAULT_MAX_TEMPERATURE_C,
        vivado_settings: Path = DEFAULT_VIVADO_SETTINGS,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        timeout_seconds: float = DEFAULT_READER_TIMEOUT_SECONDS,
        persistent_reader: bool = True,
    ):
        self.max_temperature_c = max_temperature_c
        self.vivado_settings = Path(vivado_settings)
        self.cache_seconds = cache_seconds
        self.timeout_seconds = timeout_seconds
        self._cached: ThermalStatus | None = None
        self._reader = PersistentVivadoThermalReader(self.vivado_settings, timeout_seconds=timeout_seconds) if persistent_reader else None

    def status(self, *, refresh: bool = False) -> ThermalStatus:
        if not refresh and self._cached is not None:
            age = datetime.now(UTC).timestamp() - datetime.fromisoformat(self._cached.checked_at).timestamp()
            if age <= self.cache_seconds:
                return self._cached
        self._cached = self._read_status()
        return self._cached

    def snapshot(self) -> ThermalStatus:
        if self._cached is not None:
            return self._cached
        return ThermalStatus(
            available=False,
            temperature_c=None,
            max_temperature_c=self.max_temperature_c,
            reason="FPGA thermal status has not been checked yet",
            checked_at=datetime.now(UTC).isoformat(),
        )

    def assert_available(self) -> ThermalStatus:
        status = self.status(refresh=True)
        if not status.available:
            raise HardwareUnavailable(status.reason or "FPGA is currently unavailable", status=status)
        return status

    def stop(self) -> None:
        if self._reader is not None:
            self._reader.stop()

    def _read_status(self) -> ThermalStatus:
        checked_at = datetime.now(UTC).isoformat()
        if not self.vivado_settings.exists():
            return ThermalStatus(False, None, self.max_temperature_c, f"Vivado settings not found at {self.vivado_settings}", checked_at)
        payload = self._read_payload()
        if payload.get("error"):
            return ThermalStatus(False, None, self.max_temperature_c, str(payload["error"]), checked_at)
        temperature = payload.get("temperature_c")
        if not isinstance(temperature, int | float):
            return ThermalStatus(False, None, self.max_temperature_c, "FPGA temperature reading was unavailable", checked_at)
        temperature_c = float(temperature)
        if temperature_c >= self.max_temperature_c:
            return ThermalStatus(False, temperature_c, self.max_temperature_c, f"FPGA is currently unavailable: temperature {temperature_c:.1f} °C is at/above {self.max_temperature_c:.1f} °C", checked_at)
        return ThermalStatus(True, temperature_c, self.max_temperature_c, None, checked_at)

    def _read_payload(self) -> dict[str, object]:
        if self._reader is not None:
            try:
                return self._reader.read_temperature()
            except Exception as exc:
                self._reader.stop()
                return {"error": f"persistent Vivado thermal reader failed: {exc}"}
        return _read_temperature_once(self.vivado_settings, timeout_seconds=self.timeout_seconds)


class PersistentVivadoThermalReader:
    def __init__(self, vivado_settings: Path, *, timeout_seconds: float):
        self.vivado_settings = Path(vivado_settings)
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def read_temperature(self) -> dict[str, object]:
        with self._lock:
            process = self._ensure_process()
            assert process.stdin is not None
            process.stdin.write("read\n")
            process.stdin.flush()
            return self._read_payload_line(process)

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.write("quit\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        script_path = _write_persistent_tcl_script()
        self._process = subprocess.Popen(
            ["bash", "-lc", f"source {self.vivado_settings} >/dev/null 2>&1 && vivado -mode batch -source {script_path}"],
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        ready = _read_until_marker(self._process, "FPGA_THERMAL_READY", timeout_seconds=self.timeout_seconds)
        script_path.unlink(missing_ok=True)
        if ready.get("error"):
            self.stop()
            raise RuntimeError(str(ready["error"]))
        return self._process

    def _read_payload_line(self, process: subprocess.Popen[str]) -> dict[str, object]:
        payload = _read_until_marker(process, "FPGA_THERMAL_JSON:", timeout_seconds=self.timeout_seconds)
        if payload.get("line"):
            extracted = _extract_payload(str(payload["line"]))
            if extracted is not None:
                return extracted
        return {"error": payload.get("error") or "Vivado temperature output did not include a thermal reading"}


class BoardWiper:
    def __init__(self, *, vivado_settings: Path = DEFAULT_VIVADO_SETTINGS, xsdb: Path = DEFAULT_XSDB, timeout_seconds: float = 60):
        self.vivado_settings = Path(vivado_settings)
        self.xsdb = Path(xsdb)
        self.timeout_seconds = timeout_seconds

    def wipe(self) -> dict[str, object]:
        if not self.vivado_settings.exists():
            return {"ok": False, "error": f"Vivado settings not found at {self.vivado_settings}"}
        script_path = _write_board_wipe_xsdb_script()
        try:
            completed = subprocess.run(
                ["bash", "-lc", f"source {self.vivado_settings} >/dev/null 2>&1 && {self.xsdb} {script_path}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        finally:
            script_path.unlink(missing_ok=True)
        ok = completed.returncode == 0 and "FPGA_WIPE_DONE" in completed.stdout
        return {
            "ok": ok,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "error": None if ok else (_last_nonempty_line(completed.stderr) or _last_nonempty_line(completed.stdout) or "board wipe failed"),
        }


class HardwareUnavailable(RuntimeError):
    def __init__(self, message: str, *, status: ThermalStatus):
        super().__init__(message)
        self.status = status


def _read_temperature_once(vivado_settings: Path, *, timeout_seconds: float) -> dict[str, object]:
    script_path = _write_oneshot_tcl_script()
    try:
        completed = subprocess.run(
            ["bash", "-lc", f"source {vivado_settings} >/dev/null 2>&1 && vivado -mode batch -source {script_path}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(90, timeout_seconds),
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        return {"error": _last_nonempty_line(completed.stderr) or _last_nonempty_line(completed.stdout) or "failed to read FPGA temperature"}
    payload = _extract_payload(completed.stdout)
    return payload or {"error": "Vivado temperature output did not include a thermal reading"}


def _write_oneshot_tcl_script() -> Path:
    return _write_temp_tcl_script(_TCL_SETUP + "\nread_temperature\nexit\n")


def _write_persistent_tcl_script() -> Path:
    return _write_temp_tcl_script(_TCL_SETUP + "\nputs {FPGA_THERMAL_READY}\nflush stdout\nwhile {[gets stdin line] >= 0} {\n    if {$line eq {read}} { read_temperature }\n    if {$line eq {quit}} { exit }\n}\n")


def _write_board_wipe_xsdb_script() -> Path:
    return _write_temp_tcl_script(r"""
connect
catch {
    targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    stop
    rst -processor
    stop
}
targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
set ctrl [mrd -value 0xF8007000]
mwr 0xF8007000 [expr {$ctrl & ~(1 << 30)}]
after 100
mwr 0xF8007000 [expr {$ctrl | (1 << 30)}]
catch {
    targets -set -filter {name =~ "xc7z020"}
    puts [fpga -state]
}
puts {FPGA_WIPE_DONE}
exit
""".lstrip())


def _write_temp_tcl_script(content: str) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as handle:
        handle.write(content)
        return Path(handle.name)


def _read_until_marker(process: subprocess.Popen[str], marker: str, *, timeout_seconds: float) -> dict[str, object]:
    assert process.stdout is not None
    deadline = datetime.now(UTC).timestamp() + timeout_seconds
    while datetime.now(UTC).timestamp() < deadline:
        if process.poll() is not None:
            err = process.stderr.read() if process.stderr else ""
            return {"error": _last_nonempty_line(err) or f"Vivado exited with status {process.returncode}"}
        ready, _, _ = select.select([process.stdout], [], [], 0.2)
        if not ready:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        if marker in line:
            return {"line": line}
    return {"error": f"timed out waiting for {marker}"}


def _extract_payload(stdout: str) -> dict[str, object] | None:
    for line in stdout.splitlines():
        if line.startswith("FPGA_THERMAL_JSON:"):
            payload = line.removeprefix("FPGA_THERMAL_JSON:")
            if payload.startswith("temperature_c="):
                return {"temperature_c": float(payload.removeprefix("temperature_c="))}
            if payload.startswith("error="):
                return {"error": payload.removeprefix("error=")}
            return json.loads(payload)
    return None


def _last_nonempty_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


_TCL_SETUP = r"""
proc emit_error {err} {
    puts "FPGA_THERMAL_JSON:error=$err"
    flush stdout
}

proc read_temperature {} {
    if {[catch {
        set sysmons [get_hw_sysmons]
        if {[llength $sysmons] == 0} {
            error {no XADC/SYSMON available}
        }
        set temp [get_property TEMPERATURE [lindex $sysmons 0]]
        puts "FPGA_THERMAL_JSON:temperature_c=$temp"
        flush stdout
    } err]} {
        emit_error $err
    }
}

if {[catch {
    open_hw_manager
    catch {disconnect_hw_server}
    connect_hw_server -allow_non_jtag
    set targets [get_hw_targets]
    if {[llength $targets] == 0} {
        error {no hardware targets available}
    }
    open_hw_target [lindex $targets 0]
} err]} {
    emit_error $err
    exit
}
""".strip()
