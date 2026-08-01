#!/usr/bin/env python3
"""Flash an AT89C2051 through the Nano-hosted programmer.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

    python flash.py COM5 firmware.ihx        # erase, write, verify
    python flash.py COM5 --signature         # check wiring only
    python flash.py COM5 --read out.bin

The signature check is worth running FIRST every time. It costs a second and
distinguishes "the 12 V rail is not switching" from "my code is wrong", which
on a part with no debug interface is most of the diagnostic information
available.
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial            # pyserial
except ImportError:
    print("error: pyserial not installed.  conda install -n embedded pyserial",
          file=sys.stderr)
    raise SystemExit(2)

FLASH_SIZE = 2048


def read_ihx(path: str) -> bytes:
    """Parse Intel HEX, which is what SDCC emits (.ihx).

    Only record types 00 (data) and 01 (EOF) are handled. Extended-address
    records cannot occur in a 2 KB part, so encountering one means the file is
    for a different chip -- worth failing on rather than ignoring.
    """
    data = bytearray(b"\xff" * FLASH_SIZE)
    highest = 0

    with open(path, "r", encoding="ascii") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or not line.startswith(":"):
                continue
            raw = bytes.fromhex(line[1:])
            count, addr, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]

            if (sum(raw) & 0xFF) != 0:
                raise SystemExit(f"{path}:{lineno}: bad checksum")
            if rtype == 1:
                break
            if rtype in (2, 4):
                raise SystemExit(
                    f"{path}:{lineno}: extended-address record - this file is "
                    "not for a 2 KB part")
            if rtype != 0:
                continue

            end = addr + count
            if end > FLASH_SIZE:
                raise SystemExit(
                    f"{path}:{lineno}: record reaches 0x{end:04X}, past the "
                    f"AT89C2051's {FLASH_SIZE}-byte flash")
            data[addr:end] = raw[4:4 + count]
            highest = max(highest, end)

    return bytes(data[:highest])


def expect(ser: serial.Serial, want: str, what: str) -> str:
    """Read lines until one starts with `want`, failing on ERR."""
    deadline = time.time() + 30
    while time.time() < deadline:
        line = ser.readline().decode("ascii", "replace").strip()
        if not line:
            continue
        if line.startswith("ERR"):
            raise SystemExit(f"{what}: {line}")
        if line.startswith(want):
            return line
    raise SystemExit(f"{what}: timed out waiting for {want!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("hexfile", nargs="?")
    ap.add_argument("--signature", action="store_true")
    ap.add_argument("--read", metavar="OUT")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=2)
    # The Nano resets when the port opens; wait for the bootloader and banner.
    time.sleep(2.0)
    ser.reset_input_buffer()

    # Always identify the part first. A wrong signature means the wiring or the
    # 12 V rail is at fault, and nothing after this point would be meaningful.
    ser.write(b"S\n")
    sig = expect(ser, "SIG", "signature")
    print(sig)
    expect(ser, "OK", "signature")

    if args.signature:
        return 0

    if args.read:
        ser.write(f"R{FLASH_SIZE}\n".encode())
        out = bytearray()
        while len(out) < FLASH_SIZE * 2:
            line = ser.readline().decode("ascii", "replace").strip()
            if line.startswith("OK"):
                break
            if line.startswith("ERR"):
                raise SystemExit(line)
            out.extend(line.encode())
        with open(args.read, "wb") as fh:
            fh.write(bytes.fromhex(out.decode()[:FLASH_SIZE * 2]))
        print(f"read {FLASH_SIZE} bytes -> {args.read}")
        return 0

    if not args.hexfile:
        ap.error("a hex file is required unless --signature or --read is given")

    image = read_ihx(args.hexfile)
    print(f"{args.hexfile}: {len(image)} bytes "
          f"({100 * len(image) // FLASH_SIZE}% of flash)")

    print("erasing...")
    ser.write(b"E\n")
    expect(ser, "OK", "erase")

    print(f"writing {len(image)} bytes...")
    ser.write(f"W{len(image)}\n".encode())
    expect(ser, "RDY", "write handshake")

    # Sent in chunks so the Nano's 64-byte serial buffer is never overrun; it
    # verifies each byte as it goes and will report the exact failing address.
    payload = image.hex().upper().encode()
    for i in range(0, len(payload), 32):
        ser.write(payload[i:i + 32])
        ser.flush()

    expect(ser, "OK", "write")
    print("done - every byte verified as written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
