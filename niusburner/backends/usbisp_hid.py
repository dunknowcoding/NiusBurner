"""
USB-ISP HID backend — zhifengsoft VID 03EB / PID C8B4.

Uses the Windows HID class driver (HidUsb) — same driver as ProgISP.
Do not replace HidUsb with WinUSB via Zadig.

HID report descriptor (read from the device)
--------------------------------------------
  FR1 FEATURE  7 data bytes   command + 4-byte SPI
  FR2 FEATURE  135 data bytes page buffer (not used for 4-byte SPI)
  FR3 FEATURE  127 data bytes page-read buffer
  FR4 FEATURE  15 data bytes  unused here

ProgISP 1.72 HID sequence (captured 2026-08-26, AT89S52 signature read)
----------------------------------------------------------------------
  SET FR1 8 bytes. Report id is always 0x01. Never pad to 136; never SET
  FR2 with zeros — that USB-resets the dongle.

  0x0F  identify     01 0F 01 00 00 00 02 00
  0x0D  connect      01 0D 00 01 20 A0 40 C0
                     01 0D 01 01 20 A0 40 C0   (target VCC + clock)
  0x0E  SPI xfer     01 0E b0 b1 b2 b3 00 04
  GET FR1 8 bytes    first 4 bytes are SPI RX; payload is byte [3]
  0x0B  disconnect   01 0B 01 00 00 00 00 00

AT89S51/S52 serial-ISP
----------------------
  Enable  : TX AC 53 00 00  RX[3] == 0x69
  Erase   : TX AC 80 00 00  wait >= 510 ms
  Sig[i]  : TX 28 0i 00 00  RX[3] = signature byte i
  Rd byte : TX 20 hi lo 00  RX[3] = program memory
  Wr byte : TX 40 hi lo data wait >= 1.5 ms
"""

from __future__ import annotations

import pathlib
import time

_VID = 0x03EB
_PID = 0xC8B4
_ISP_ACK = 0x69
_ERASE_MS = 520
_WRITE_MS = 5
_FR1_LEN = 8
_AT89S52_SIG = (0x1E, 0x52, 0x06)


def _spi_rx(raw: list[int]) -> list[int]:
    """Pull 4 SPI RX bytes out of a Feature Report 1 GET.

    ProgISP reads 8 bytes with no extra report-id prefix; hidapi on Windows
    may insert a leading 0x01. Trailing 0x60 0xFF bytes are stale SRAM.
    """
    if not raw:
        return [0, 0, 0, 0]
    data = list(raw)
    if data[0] == 0x01 and len(data) > 4:
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
        self._connected = False

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
            if self._connected:
                self.disconnect()
        except Exception:
            pass
        try:
            self._dev.close()
        except Exception:
            pass

    def __enter__(self) -> "_Programmer":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _fr1(self, payload7: list[int]) -> None:
        buf = bytes([0x01] + list(payload7[:7]))
        if len(buf) != _FR1_LEN:
            buf = (buf + bytes(_FR1_LEN))[:_FR1_LEN]
        self._dev.send_feature_report(buf)

    def _fr1_get(self) -> list[int]:
        raw = self._dev.get_feature_report(0x01, _FR1_LEN)
        return _spi_rx(list(raw) if raw else [])

    def identify(self) -> None:
        self._fr1([0x0F, 0x01, 0x00, 0x00, 0x00, 0x02, 0x00])
        time.sleep(0.02)
        try:
            self._fr1_get()
        except OSError:
            pass

    def connect(self) -> None:
        """Enable target VCC and clock, then hold AT89S52 RST high."""
        self._fr1([0x0D, 0x00, 0x01, 0x20, 0xA0, 0x40, 0xC0])
        time.sleep(0.02)
        self._fr1([0x0D, 0x01, 0x01, 0x20, 0xA0, 0x40, 0xC0])
        time.sleep(0.05)
        self._connected = True

    def disconnect(self) -> None:
        self._fr1([0x0B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
        self._connected = False
        time.sleep(0.02)

    def spi(self, b0: int, b1: int, b2: int, b3: int,
            wait_ms: int = 5) -> list[int]:
        """Execute one 4-byte SPI transaction; return 4 RX bytes."""
        self._fr1([0x0E, b0, b1, b2, b3, 0x00, 0x04])
        time.sleep(wait_ms / 1000)
        return self._fr1_get()

    def enter_isp(self, retries: int = 8) -> None:
        """Identify, connect (VCC+clock+RST), enable programming for 0x69."""
        last = "no response"
        self.identify()
        for attempt in range(retries):
            if self._connected:
                self.disconnect()
            self.connect()
            rx = self.spi(0xAC, 0x53, 0x00, 0x00, wait_ms=20)
            if rx[3] == _ISP_ACK:
                return
            last = f"RX {' '.join(f'{b:02X}' for b in rx)}"
            time.sleep(0.05)
        raise RuntimeError(
            f"ISP enable: no 0x69 ACK ({last}). "
            "AT89S52 serial-ISP: AC 53 00 00, ACK in SPI byte 3. "
            "Check IDC10 pin-1, MOSI/MISO/SCK/RST, and that the socket "
            "holds AT89S51/S52. See docs/wiring/usbasp-idc10.md.")

    def read_signature(self) -> tuple[int, int, int]:
        return (
            self.spi(0x28, 0, 0, 0)[3],
            self.spi(0x28, 1, 0, 0)[3],
            self.spi(0x28, 2, 0, 0)[3],
        )

    def chip_erase(self) -> None:
        self.spi(0xAC, 0x80, 0x00, 0x00, wait_ms=_ERASE_MS)
        # Erase drops programming-enable; pulse RST and send AC 53 again.
        self.enter_isp()

    def read_byte(self, addr: int) -> int:
        return self.spi(0x20, addr >> 8, addr & 0xFF, 0x00)[3]

    def write_byte(self, addr: int, data: int) -> None:
        self.spi(0x40, addr >> 8, addr & 0xFF, data, wait_ms=_WRITE_MS)
        if data == 0xFF:
            return
        for _ in range(20):
            if self.read_byte(addr) == data:
                return
            time.sleep(0.001)


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
            if sig == _AT89S52_SIG:
                print("Probe OK - AT89S52, ISP session live (chip not erased).")
            else:
                print("Probe OK — ISP session is live (chip not erased).")
                print("warning: signature is not the AT89S52 1E 52 06")
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1
    except OSError as exc:
        print(f"error: HID I/O failed: {exc}")
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
            if target.lower() == "at89s52" and sig != _AT89S52_SIG:
                print("error: signature is not AT89S52 (1E 52 06); refusing erase")
                return 1

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

            print("Done - ISP complete.")
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1
    except OSError as exc:
        print(f"error: HID I/O failed: {exc}")
        return 1
    return 0
