"""Read the AT89S52 UART from a host serial port (CH341).

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

USB-ISP flashing is HID, not this COM port. The CH341 is only Serial:
MCU P3.1/TXD -> adapter RXD, MCU P3.0/RXD -> adapter TXD.

COM35 is refused: that port is not this board's UART.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Callable

BLOCKED_PORTS = frozenset({"COM35", "COM35:"})

_BEGIN = re.compile(
    r"(?:Serial\.begin|nius_serial_begin)\s*\(\s*(\d+)",
    re.MULTILINE,
)


def uart_baud_from_sketch(text: str) -> int | None:
    """Baud in Serial.begin / nius_serial_begin, if the sketch writes one."""
    match = _BEGIN.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def _normalize_port(port: str) -> str:
    return port.strip().upper().rstrip(":")


def monitor(port: str, baud: int, seconds: float | None = None,
            expect: str | None = None,
            on_open: "Callable[[], None] | None" = None) -> int:
    """Read *port* at *baud*, printing bytes as they arrive.

    *on_open* runs once the port is open and drained. That ordering is the
    whole point for a freshly flashed part: reset it any earlier and the
    banner it prints in its first milliseconds is gone before Windows has
    finished opening the COM port.
    """
    name = _normalize_port(port)
    if name in BLOCKED_PORTS or name.startswith("COM35"):
        print(
            "refused: COM35 is not the AT89S52 UART. "
            "Use the CH341 port (this bench: COM31).",
            file=sys.stderr,
        )
        return 2
    try:
        import serial  # type: ignore
    except ImportError:
        print("pyserial is required:  pip install pyserial", file=sys.stderr)
        return 2
    try:
        # Many 8051 boards wire CH341 DTR/RTS to RST. pyserial asserts DTR on
        # open by default and that holds the AT89S52 in reset — 0 bytes.
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.timeout = 0.2
        ser.dtr = False
        ser.rts = False
        ser.open()
        ser.dtr = False
        ser.rts = False
    except OSError as exc:
        print(f"monitor failed to open {port}: {exc}", file=sys.stderr)
        return 2
    print(f"monitor  {port}  {baud} 8N1", file=sys.stderr)
    if on_open is not None:
        ser.reset_input_buffer()
        try:
            on_open()
        except Exception as exc:            # noqa: BLE001 - reported, not raised
            print(f"monitor: reset hook failed: {exc}", file=sys.stderr)
            ser.close()
            return 2
    deadline = None if seconds is None else (time.monotonic() + seconds)
    received = bytearray()
    try:
        while deadline is None or time.monotonic() < deadline:
            chunk = ser.read(256)
            if chunk:
                received.extend(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        print(file=sys.stderr)
    finally:
        ser.close()
    if expect:
        needle = expect.encode("ascii", errors="replace")
        if needle not in bytes(received):
            print(
                f"monitor: did not see {expect!r} "
                f"({len(received)} byte(s) read)",
                file=sys.stderr,
            )
            return 1
    return 0
