"""
USB-ISP HID backend — zhifengsoft VID 03EB / PID C8B4.

Protocol (reverse-engineered, 2026-08-26):
  Feature Report 1 (7 data bytes): SPI TX buffer — SET to load 4 SPI bytes.
  Feature Report 2 (135 data bytes): SPI execute — SET (any data) fires SPI;
      programmer disconnects if MISO is all-zero (no target detected).
  Feature Report 1 GET: returns SPI RX bytes [r0, r1, r2, r3, pad, pad, pad].

AT89S / STC89C ISP programming notes
-------------------------------------
  Enter ISP:  TX [AC 53 00 00] → RX byte[2] must be 0x69
  Chip erase: TX [AC 80 00 00] → wait 510 ms
  Read flash: TX [20 addr_hi addr_lo 00] → RX byte[3] = data
  Write byte: TX [40 addr_hi addr_lo data] → wait 1.5 ms
  Read sig:   TX [28 i 00 00] → RX byte[3] = sig[i]  (i = 0,1,2)
  Exit ISP:   pull RST high (programmer does this on disconnect)

Hardware requirements
---------------------
  Target board must be independently powered (USB or power adapter).
  ISP programmer VCC pin is sense-only — do not rely on it to power the board.
  IDC10 pin-1 triangle must align with the board header pin-1 mark.
  A crystal is mandatory on AT89S52; STC89C52RC accepts internal RC but a
  crystal is strongly recommended — without a running clock ISP never responds.
"""

from __future__ import annotations

import pathlib
import time

_DLL_REL = (r"libusb\_platform\windows\x86_64\libusb-1.0.dll")

_PROG_VID = 0x03EB
_PROG_PID = 0xC8B4
_IFACE    = 0


def _find_dll() -> str:
    import sys, importlib.util
    spec = importlib.util.find_spec("libusb")
    if spec and spec.submodule_search_locations:
        base = pathlib.Path(list(spec.submodule_search_locations)[0])
        dll = base / "_platform" / "windows" / "x86_64" / "libusb-1.0.dll"
        if dll.exists():
            return str(dll)
    raise FileNotFoundError(
        "libusb-1.0.dll not found; install the 'libusb' Python package")


def _open():
    import usb.core, usb.backend.libusb1
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: _find_dll())
    dev = usb.core.find(idVendor=_PROG_VID, idProduct=_PROG_PID, backend=backend)
    if dev is None:
        raise FileNotFoundError(
            f"USB-ISP programmer not found "
            f"(VID {_PROG_VID:04X} / PID {_PROG_PID:04X}); "
            "check USB connection and WinUSB driver via Zadig")
    try:
        dev.set_configuration()
    except Exception:
        pass
    return dev


def _spi(dev, b0: int, b1: int, b2: int, b3: int) -> list[int]:
    """Execute one 4-byte SPI transaction; return 4 RX bytes."""
    import usb.core
    # Load TX bytes into Feature Report 1 (7 data bytes)
    dev.ctrl_transfer(0x21, 0x09, 0x0301, _IFACE,
                      bytes([0x01, b0, b1, b2, b3, 0x00, 0x00]))
    time.sleep(0.005)
    # Trigger SPI execution via Feature Report 2 write (any payload)
    try:
        dev.ctrl_transfer(0x21, 0x09, 0x0302, _IFACE, bytes([0x02] + [0] * 135))
    except usb.core.USBError:
        raise RuntimeError(
            "SPI execute triggered a disconnect — "
            "target chip not present or MISO unresponsive. "
            "Check: board powered, crystal running, IDC10 pin-1 aligned.")
    time.sleep(0.030)
    r = dev.ctrl_transfer(0xA1, 0x01, 0x0301, _IFACE, 8)
    return list(r[1:5])          # bytes 1-4 are the 4 SPI RX bytes


def _isp_enter(dev, retries: int = 32) -> None:
    """Assert RST low and enable ISP programming on the target."""
    import usb.core
    for attempt in range(retries):
        try:
            rx = _spi(dev, 0xAC, 0x53, 0x00, 0x00)
        except RuntimeError as exc:
            raise RuntimeError(f"ISP enter failed (attempt {attempt + 1}): {exc}") from exc
        if rx[2] == 0x69:
            return
        time.sleep(0.025)
    raise RuntimeError(
        f"ISP enable: no 0x69 ACK after {retries} retries. "
        "Verify target power, crystal, and ISP cable orientation.")


def _ihx_to_pages(ihx_path: pathlib.Path) -> dict[int, int]:
    """Parse Intel HEX → {address: byte}."""
    data: dict[int, int] = {}
    for line in ihx_path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        rec_len = int(line[1:3], 16)
        address = int(line[3:7], 16)
        rec_type = int(line[7:9], 16)
        if rec_type == 0x00:       # data record
            for i in range(rec_len):
                data[address + i] = int(line[9 + i * 2: 11 + i * 2], 16)
        elif rec_type == 0x01:     # end of file
            break
    return data


def flash(image: pathlib.Path, target: str) -> int:
    """
    Erase, program, and verify *image* (.ihx) on the target chip.
    Returns 0 on success, non-zero on failure.
    """
    print(f"Opening programmer VID {_PROG_VID:04X} / PID {_PROG_PID:04X} …")
    try:
        dev = _open()
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1

    print("Entering ISP mode …")
    try:
        _isp_enter(dev)
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1

    # Read and print signature for confirmation
    sig = [_spi(dev, 0x28, i, 0, 0)[3] for i in range(3)]
    print(f"Chip signature: {[f'0x{b:02X}' for b in sig]}")

    print("Erasing …")
    _spi(dev, 0xAC, 0x80, 0x00, 0x00)
    time.sleep(0.510)

    print(f"Programming {image.name} …")
    data = _ihx_to_pages(image)
    if not data:
        print("error: image is empty or not valid Intel HEX")
        return 1

    addresses = sorted(data)
    for addr in addresses:
        byte = data[addr]
        _spi(dev, 0x40, addr >> 8, addr & 0xFF, byte)
        time.sleep(0.0015)
    print(f"  wrote {len(addresses)} bytes")

    print("Verifying …")
    errors = 0
    for addr, expected in data.items():
        actual = _spi(dev, 0x20, addr >> 8, addr & 0xFF, 0x00)[3]
        if actual != expected:
            print(f"  verify mismatch at 0x{addr:04X}: wrote 0x{expected:02X}, read 0x{actual:02X}")
            errors += 1
    if errors:
        print(f"  {errors} verify error(s)")
        return 1

    print("Done — ISP complete, RST released.")
    return 0
