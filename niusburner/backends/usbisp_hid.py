"""
USB-ISP HID backend — zhifengsoft VID 03EB / PID C8B4.

Uses the Windows HID class driver (HidUsb) — same driver as ProgISP.
Do not replace HidUsb with WinUSB via Zadig.

HID report descriptor (read from the device, 2026-08-26)
--------------------------------------------------------
  FR1 FEATURE  7 data bytes   command / 4-byte SPI buffer
  FR2 FEATURE  135 data bytes execute (1+7+128: header + flash page)
  FR3 FEATURE  127 data bytes page-read buffer
  FR4 FEATURE  15 data bytes  status / control

Observed host sequence
----------------------
  SET FR1  → load 4 SPI TX bytes
  SET FR2  → execute. The transfer itself STALLs or returns -1; that is
             normal. If the target MISO line stays 0, the programmer then
             USB-resets (disconnect + re-enumerate). That is NOT a
             successful SPI cycle — it means no clocked reply from the chip.
  GET FR1  → 4 SPI RX bytes, only valid if the handle survived SET FR2.

AT89S51/S52 serial-ISP commands (not the STC UART bootloader)
-------------------------------------------------------------
  Enable  : TX AC 53 00 00  RX byte[2] must be 0x69
  Erase   : TX AC 80 00 00  wait >= 510 ms
  Sig[i]  : TX 28 0i 00 00  RX byte[3] = sig byte i  (i = 0, 1, 2)
  Rd byte : TX 20 hi lo 00  RX byte[3] = program memory byte
  Wr byte : TX 40 hi lo data wait >= 1.5 ms per byte

STC89C52RC silicon speaks the UART bootloader, not this SPI state
machine. SPI ACK is only expected when the DIP-40 socket holds an
AT89S51/S52 (or another part that implements the Atmel serial protocol).
"""

from __future__ import annotations

import pathlib
import time

_VID = 0x03EB
_PID = 0xC8B4
_ISP_ACK = 0x69
_ERASE_MS = 520
_WRITE_MS = 2
_FR1_DATA = 7
_FR2_DATA = 135
_RECONNECT_S = 2.0


class _TargetSilent(RuntimeError):
    """Programmer USB-reset because the target did not drive MISO."""


def _spi_rx(raw: list[int]) -> list[int]:
    """Pull 4 SPI RX bytes out of a Feature Report 1 GET.

    hidapi on Windows may omit the report-id byte, include it as 0x01,
    and append one uninitialised trailing byte. None of those extras are SPI.
    """
    if not raw:
        return [0, 0, 0, 0]
    data = list(raw)
    if data[0] == 0x01:
        data = data[1:]
    data = data[:4]
    return data + [0] * (4 - len(data))


def _parse_ihx(path: pathlib.Path) -> dict[int, int]:
    """Return {address: byte} for all data records in an Intel HEX file."""
    data: dict[int, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        length = int(line[1:3], 16)
        address = int(line[3:7], 16)
        rec_type = int(line[7:9], 16)
        if rec_type == 0x00:
            for i in range(length):
                data[address + i] = int(line[9 + i * 2: 11 + i * 2], 16)
        elif rec_type == 0x01:
            break
    return data


class _Programmer:
    """Thin wrapper over the HID device; owns open/close lifetime."""

    def __init__(self) -> None:
        try:
            import hid as _hid
        except ImportError as exc:
            raise ImportError(
                "hidapi is required: pip install hidapi") from exc
        self._hid = _hid
        self._dev = _hid.device()

    def open(self) -> None:
        devs = self._hid.enumerate(_VID, _PID)
        if not devs:
            raise FileNotFoundError(
                f"USB-ISP programmer not found "
                f"(VID {_VID:04X} / PID {_PID:04X}). "
                "Driver must be HidUsb. "
                "If WinUSB is active, revert via Zadig → HidUsb → Replace Driver. "
                "See docs/wiring/usbasp-idc10.md.")
        iface = min(devs, key=lambda d: d["interface_number"])
        self._dev.open_path(iface["path"])

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass

    def __enter__(self) -> "_Programmer":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _wait_present(self, timeout: float = _RECONNECT_S) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._hid.enumerate(_VID, _PID):
                return True
            time.sleep(0.1)
        return False

    def _reopen(self) -> None:
        self.close()
        if not self._wait_present():
            raise FileNotFoundError(
                "USB-ISP programmer disappeared after SPI execute and "
                "did not re-enumerate.")
        self._dev = self._hid.device()
        self.open()

    def _fr1_set(self, b0: int, b1: int, b2: int, b3: int) -> None:
        payload = [b0, b1, b2, b3, 0x00, 0x00, 0x00]
        self._dev.send_feature_report(bytes([0x01] + payload[:_FR1_DATA]))

    def _fr2_execute(self) -> None:
        """Fire SPI. A STALL / -1 on the SET itself is expected.

        A subsequent GET failure means the programmer USB-reset: the target
        did not drive MISO. That is raised as _TargetSilent rather than
        retried blindly — each retry unplugs the device.
        """
        try:
            n = self._dev.send_feature_report(bytes([0x02] + [0x00] * _FR2_DATA))
        except OSError as exc:
            raise _TargetSilent(f"SET FR2 raised: {exc}") from exc
        if isinstance(n, int) and n < 0:
            # hidapi returns -1 instead of raising on a STALL. GET decides
            # whether this was "fired" or "device gone".
            return

    def _fr1_get(self) -> list[int]:
        raw = self._dev.get_feature_report(0x01, _FR1_DATA + 1)
        return _spi_rx(list(raw) if raw else [])

    def spi(self, b0: int, b1: int, b2: int, b3: int,
            wait_ms: int = 80) -> list[int]:
        """Execute one 4-byte SPI transaction; return 4 RX bytes."""
        self._fr1_set(b0, b1, b2, b3)
        self._fr2_execute()
        time.sleep(wait_ms / 1000)
        try:
            return self._fr1_get()
        except OSError as exc:
            raise _TargetSilent(
                "programmer USB-reset during SPI execute "
                "(target MISO stayed 0)") from exc

    def enter_isp(self, retries: int = 4) -> None:
        """Assert RST, enable ISP, wait for 0x69 ACK.

        Stops after a USB-reset rather than hammering the programmer.
        """
        last = "no response"
        for attempt in range(retries):
            try:
                rx = self.spi(0xAC, 0x53, 0x00, 0x00, wait_ms=200)
            except _TargetSilent as exc:
                last = str(exc)
                if attempt + 1 < retries:
                    self._reopen()
                    continue
                break
            if rx[2] == _ISP_ACK:
                return
            last = f"RX {' '.join(f'{b:02X}' for b in rx)}"
            time.sleep(0.05)
        raise RuntimeError(
            f"ISP enable: no 0x69 ACK ({last}). "
            "USB-ISP SPI is the AT89S51/S52 protocol. "
            "STC89C52RC in the same DIP-40 socket uses the UART bootloader, "
            "not this header. Also check: board powered, crystal running, "
            "IDC10 pin-1 aligned. See docs/wiring/usbasp-idc10.md.")

    def read_signature(self) -> tuple[int, int, int]:
        return (
            self.spi(0x28, 0, 0, 0)[3],
            self.spi(0x28, 1, 0, 0)[3],
            self.spi(0x28, 2, 0, 0)[3],
        )

    def chip_erase(self) -> None:
        self.spi(0xAC, 0x80, 0x00, 0x00, wait_ms=_ERASE_MS)

    def read_byte(self, addr: int) -> int:
        return self.spi(0x20, addr >> 8, addr & 0xFF, 0x00)[3]

    def write_byte(self, addr: int, data: int) -> None:
        self.spi(0x40, addr >> 8, addr & 0xFF, data, wait_ms=_WRITE_MS)


def _programmer_or_report() -> _Programmer | int:
    try:
        return _Programmer()
    except ImportError as exc:
        print(f"error: {exc}")
        return 1


def probe(target: str) -> int:
    """Open the programmer, try ISP enable, print signature. No erase."""
    print(f"Programmer  VID {_VID:04X} / PID {_PID:04X}  ({target})")
    prog = _programmer_or_report()
    if isinstance(prog, int):
        return prog
    try:
        with prog:
            print("Entering ISP mode ...")
            try:
                prog.enter_isp()
            except RuntimeError as exc:
                print(f"error: {exc}")
                return 1
            sig = prog.read_signature()
            print(f"Signature   0x{sig[0]:02X} 0x{sig[1]:02X} 0x{sig[2]:02X}")
            print("Probe OK — ISP session is live (chip not erased).")
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1
    return 0


def flash(image: pathlib.Path, target: str) -> int:
    """Erase, program and verify *image* (.ihx) on the target. Returns 0 on success."""
    print(f"Programmer  VID {_VID:04X} / PID {_PID:04X}  ({target})")

    prog = _programmer_or_report()
    if isinstance(prog, int):
        return prog

    try:
        with prog:
            print("Entering ISP mode ...")
            try:
                prog.enter_isp()
            except RuntimeError as exc:
                print(f"error: {exc}")
                return 1

            sig = prog.read_signature()
            print(f"Signature   0x{sig[0]:02X} 0x{sig[1]:02X} 0x{sig[2]:02X}")

            print("Erasing ...")
            prog.chip_erase()

            data = _parse_ihx(image)
            if not data:
                print("error: image is empty or not valid Intel HEX")
                return 1

            print(f"Programming {len(data)} bytes ...")
            for addr in sorted(data):
                prog.write_byte(addr, data[addr])

            print("Verifying ...")
            errors = 0
            for addr, expected in sorted(data.items()):
                actual = prog.read_byte(addr)
                if actual != expected:
                    print(f"  0x{addr:04X}: wrote 0x{expected:02X}, read 0x{actual:02X}")
                    errors += 1
            if errors:
                print(f"  {errors} verify error(s)")
                return 1

            print("Done — ISP complete.")
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1
    return 0
