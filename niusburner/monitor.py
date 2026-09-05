"""Read the AT89S52 UART from a host serial port (CH341).

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

USB-ISP flashing is HID, not this COM port. The CH341 is only Serial:
MCU P3.1/TXD -> adapter RXD, MCU P3.0/RXD -> adapter TXD.

COM35 is refused: that port is not this board's UART.
"""

from __future__ import annotations

import math
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


#: Crystals a board in this catalog is plausibly fitted with. A legacy board
#: carries whatever its designer had to hand: 11.0592 for exact serial rates,
#: 12 for round instruction timing, 22.1184 for both at speed.
CRYSTALS = (4_000_000, 8_000_000, 11_059_200, 12_000_000,
            16_000_000, 20_000_000, 22_118_400, 24_000_000)

#: Everything a part is likely to print, plus the whitespace it prints it
#: with. Anything much outside this is not text arriving slightly wrong; it
#: is text arriving at the wrong rate.
_TEXTUAL = frozenset(b"\t\r\n") | frozenset(range(0x20, 0x7F))


def looks_like_text(data: bytes, threshold: float = 0.85) -> bool:
    """Whether *data* reads as a part talking, rather than as framing noise.

    A UART reading a line clocked at the wrong rate does not fall silent --
    it samples in the middle of somebody else's bits and hands back bytes
    that are mostly outside printable ASCII. Very short reads are called
    text: one or two odd bytes at the start of a capture are normal, and
    guessing off them would be worse than saying nothing.
    """
    if len(data) < 8:
        return True
    good = sum(1 for byte in data if byte in _TEXTUAL)
    return good >= threshold * len(data)


def clock_candidates(baud: int, f_cpu: int,
                     crystals: "tuple[int, ...]" = CRYSTALS
                     ) -> "list[tuple[int, int]]":
    """(crystal, rate) for each crystal the board might have instead.

    Every serial rate on these parts is the clock divided by something, so a
    board fitted with a crystal other than the one the image was built for
    talks at a proportionally different rate -- and at no point reports that
    it is doing so.
    """
    if baud <= 0 or f_cpu <= 0:
        return []
    out = [(hz, round(baud * hz / f_cpu)) for hz in crystals if hz != f_cpu]
    # Nearest ratio first: the closest crystal is the likeliest mistake.
    # The distance is measured on a log scale because the error is a
    # multiple, not a difference -- half the clock is as wrong as twice it,
    # and ranking on the plain difference buries 20 MHz (1.8x out) under
    # 4 MHz (2.8x out) purely for being on the low side.
    out.sort(key=lambda item: abs(math.log(item[0] / f_cpu)))
    return out


def _mhz(hz: int) -> str:
    text = f"{hz / 1_000_000:.4f}".rstrip("0").rstrip(".")
    return f"{text} MHz"


def clock_mismatch_hint(baud: int, f_cpu: int, limit: int = 4) -> str:
    """What to say when the bytes are not text and the clock could be why."""
    candidates = clock_candidates(baud, f_cpu)[:limit]
    if not candidates:
        return ""
    lines = [
        "monitor: these bytes are not text. The image was built for a "
        f"{_mhz(f_cpu)} crystal;",
        "         a board fitted with a different one talks at a different "
        "rate:",
        "",
    ]
    lines += [f"           {_mhz(hz):>12}  ->  {rate} baud"
              for hz, rate in candidates]
    lines += [
        "",
        "         Set Tools -> Clock (or --f-cpu) to the crystal actually "
        "fitted",
        "         and upload again.",
    ]
    return "\n".join(lines)


def _normalize_port(port: str) -> str:
    return port.strip().upper().rstrip(":")


def monitor(port: str, baud: int, seconds: float | None = None,
            expect: str | None = None,
            on_open: "Callable[[], None] | None" = None,
            f_cpu: int | None = None) -> int:
    """Read *port* at *baud*, printing bytes as they arrive.

    *on_open* runs once the port is open and drained. That ordering is the
    whole point for a freshly flashed part: reset it any earlier and the
    banner it prints in its first milliseconds is gone before Windows has
    finished opening the COM port.
    """
    name = _normalize_port(port)
    if name in BLOCKED_PORTS or name.startswith("COM35"):
        print(
            "refused: COM35 is not the target UART. "
            "Use the serial adapter's port.",
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
    if f_cpu and received and not looks_like_text(bytes(received)):
        hint = clock_mismatch_hint(baud, f_cpu)
        if hint:
            print(file=sys.stderr)
            print(hint, file=sys.stderr)
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
