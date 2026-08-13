from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MAX_TEMPERATURE_C = float(os.environ.get("FPGA_DEMO_MAX_TEMPERATURE_C", "75.0"))
DEFAULT_VIVADO_SETTINGS = Path(os.environ.get("FPGA_DEMO_VIVADO_SETTINGS", "/home/njason/Xilinx/2025.2/Vivado/settings64.sh"))
DEFAULT_CACHE_SECONDS = float(os.environ.get("FPGA_DEMO_TEMPERATURE_CACHE_SECONDS", "10"))


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
    ):
        self.max_temperature_c = max_temperature_c
        self.vivado_settings = Path(vivado_settings)
        self.cache_seconds = cache_seconds
        self._cached: ThermalStatus | None = None

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

    def _read_status(self) -> ThermalStatus:
        checked_at = datetime.now(UTC).isoformat()
        if not self.vivado_settings.exists():
            return ThermalStatus(
                available=False,
                temperature_c=None,
                max_temperature_c=self.max_temperature_c,
                reason=f"Vivado settings not found at {self.vivado_settings}",
                checked_at=checked_at,
            )
        script = """
open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target [lindex [get_hw_targets] 0]
set sysmons [get_hw_sysmons]
if {[llength $sysmons] == 0} {
    puts {FPGA_THERMAL_JSON:{"temperature_c":null,"error":"no XADC/SYSMON available"}}
    exit
}
set temp [get_property TEMPERATURE [lindex $sysmons 0]]
puts "FPGA_THERMAL_JSON:temperature_c=$temp"
exit
""".strip()
        with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as handle:
            handle.write(script + "\n")
            script_path = Path(handle.name)
        try:
            completed = subprocess.run(
                ["bash", "-lc", f"source {self.vivado_settings} >/dev/null 2>&1 && vivado -mode batch -source {script_path}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
        finally:
            script_path.unlink(missing_ok=True)
        if completed.returncode != 0:
            reason = _last_nonempty_line(completed.stderr) or _last_nonempty_line(completed.stdout) or "failed to read FPGA temperature"
            return ThermalStatus(False, None, self.max_temperature_c, reason, checked_at)
        payload = _extract_payload(completed.stdout)
        if payload is None:
            return ThermalStatus(False, None, self.max_temperature_c, "Vivado temperature output did not include a thermal reading", checked_at)
        if payload.get("error"):
            return ThermalStatus(False, None, self.max_temperature_c, str(payload["error"]), checked_at)
        temperature = payload.get("temperature_c")
        if not isinstance(temperature, int | float):
            return ThermalStatus(False, None, self.max_temperature_c, "FPGA temperature reading was unavailable", checked_at)
        temperature_c = float(temperature)
        if temperature_c >= self.max_temperature_c:
            return ThermalStatus(
                available=False,
                temperature_c=temperature_c,
                max_temperature_c=self.max_temperature_c,
                reason=f"FPGA is currently unavailable: temperature {temperature_c:.1f} °C is at/above {self.max_temperature_c:.1f} °C",
                checked_at=checked_at,
            )
        return ThermalStatus(True, temperature_c, self.max_temperature_c, None, checked_at)


class HardwareUnavailable(RuntimeError):
    def __init__(self, message: str, *, status: ThermalStatus):
        super().__init__(message)
        self.status = status


def _extract_payload(stdout: str) -> dict[str, object] | None:
    for line in stdout.splitlines():
        if line.startswith("FPGA_THERMAL_JSON:"):
            payload = line.removeprefix("FPGA_THERMAL_JSON:")
            if payload.startswith("temperature_c="):
                return {"temperature_c": float(payload.removeprefix("temperature_c="))}
            return json.loads(payload)
    return None


def _last_nonempty_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None
