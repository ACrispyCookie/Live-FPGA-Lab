from __future__ import annotations

import importlib.util
import struct
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = next((ROOT / "demos").glob("*gpgpu-nbody"))
spec = importlib.util.spec_from_file_location("nbody_uart_test", DEMO / "host/baremetal/gpgpu_uart.py")
assert spec and spec.loader
uart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uart)


class MonitorSerial:
    """Byte-level monitor with a bounded reply and fragmented/coalesced reads."""

    def __init__(self, words, *, fragment=4096, truncate=False, reject=False):
        self.words = words
        self.fragment = fragment
        self.truncate = truncate
        self.reject = reject
        self.pending = bytearray()
        self.commands = []

    @property
    def in_waiting(self):
        return min(len(self.pending), self.fragment)

    def write(self, data):
        assert not self.pending.strip(), "Next request sent before prior response was drained"
        command, offset, count = data.decode().split()
        offset, count = int(offset), int(count)
        assert command == "dumpdmem_bin"
        assert count <= 8, "Unpaced large binary reply can overrun the USB-UART receive path"
        self.commands.append((offset, count))
        if self.reject:
            self.pending.extend(b"ERROR: invalid range\r\ngpgpu> ")
        else:
            raw = b"".join(struct.pack("<I", self.words[i]) for i in range(offset, offset + count))
            if self.truncate:
                raw = raw[:-3]
            self.pending.extend(b"BEGIN_DMEM_BIN\n" + raw + b"\r\ngpgpu> ")
        return len(data)

    def read(self, count):
        if not self.pending:
            time.sleep(.001)
            return b""
        count = min(count, self.fragment)
        data = bytes(self.pending[:count])
        del self.pending[:count]
        return data

    def flush(self):
        pass


def monitor(serial):
    result = uart.GpgpuUartMonitor.__new__(uart.GpgpuUartMonitor)
    result.ser = serial
    result.rx_buffer = bytearray()
    result.verbose = False
    return result


@pytest.mark.parametrize("fragment", [1, 7, 4096])
def test_binary_dump_paces_complete_chunks_and_preserves_word_offsets(fragment):
    words = {1024 + i: (i * 0x01020304) & 0xFFFFFFFF for i in range(96)}
    # Marker-like text and CR/LF inside binary must not be interpreted as framing.
    words[1028] = int.from_bytes(b"gpgp", "little")
    words[1029] = int.from_bytes(b"u>\r\n", "little")
    serial = MonitorSerial(words, fragment=fragment)
    result = monitor(serial).dump_dmem_bin(count=96, offset=1024)
    assert result == {addr: f"{word:08x}" for addr, word in words.items()}
    assert serial.commands == [(1024 + i, 8) for i in range(0, 96, 8)]


def test_binary_dump_handles_partial_final_chunk():
    serial = MonitorSerial({i: i for i in range(101, 120)})
    result = monitor(serial).dump_dmem_bin(count=19, offset=101)
    assert result == {i: f"{i:08x}" for i in range(101, 120)}
    assert serial.commands == [(101, 8), (109, 8), (117, 3)]


def test_binary_dump_never_returns_partial_result_after_truncated_reply():
    serial = MonitorSerial({i: i for i in range(19)}, truncate=True)
    client = monitor(serial)
    original_read = client.read_exact
    original_prompt = client.wait_prompt
    client.read_exact = lambda count, timeout=20: original_read(count, timeout=.02)
    client.wait_prompt = lambda timeout=20: original_prompt(timeout=.02)
    with pytest.raises(TimeoutError):
        client.dump_dmem_bin(count=19)
    assert serial.commands == [(0, 8)]


def test_binary_dump_preserves_monitor_errors():
    serial = MonitorSerial({}, reject=True)
    with pytest.raises(RuntimeError, match="DMEM binary dump rejected"):
        monitor(serial).dump_dmem_bin(count=4)


@pytest.mark.parametrize("offset,count", [(-1, 1), (0, -1), (2047, 2), (2049, 0)])
def test_invalid_full_range_is_rejected_before_partial_commands(offset, count):
    serial = MonitorSerial({})
    with pytest.raises(ValueError, match="DMEM"):
        monitor(serial).dump_dmem_bin(count=count, offset=offset)
    assert serial.commands == []
