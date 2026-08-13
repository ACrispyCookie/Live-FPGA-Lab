from fpga_demo_platform.thermal import ThermalStatus


class FakeThermalGuard:
    def __init__(self, available=True, temperature_c=45.0, reason=None):
        self._status = ThermalStatus(
            available=available,
            temperature_c=temperature_c,
            max_temperature_c=75.0,
            reason=reason,
            checked_at="2026-08-12T00:00:00+00:00",
        )

    def status(self, *, refresh=False):
        return self._status

    def snapshot(self):
        return self._status

    def assert_available(self):
        if not self._status.available:
            from fpga_demo_platform.thermal import HardwareUnavailable

            raise HardwareUnavailable(self._status.reason or "unavailable", status=self._status)
        return self._status


class BlockingThermalGuard(FakeThermalGuard):
    def status(self, *, refresh=False):
        raise AssertionError("fast API status must not probe hardware")

    def assert_available(self):
        raise AssertionError("fast API status must not assert hardware availability")


class SequenceThermalGuard:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.index = 0

    def status(self, *, refresh=False):
        if not refresh:
            return self.snapshot()
        current = self.statuses[min(self.index, len(self.statuses) - 1)]
        self.index += 1
        return current

    def snapshot(self):
        return self.statuses[min(max(self.index - 1, 0), len(self.statuses) - 1)]

    def assert_available(self):
        status = self.status(refresh=True)
        if not status.available:
            from fpga_demo_platform.thermal import HardwareUnavailable

            raise HardwareUnavailable(status.reason or "unavailable", status=status)
        return status


class FakeBoardWiper:
    def __init__(self):
        self.calls = 0

    def wipe(self):
        self.calls += 1
