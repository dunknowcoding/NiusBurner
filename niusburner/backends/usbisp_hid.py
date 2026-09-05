"""
USB-ISP HID backend for the AT89S51/S52 serial programming protocol.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Device: USB VID 03EB / PID C8B4, driven through the Windows HID class
driver (HidUsb). Do not replace HidUsb with WinUSB via Zadig.

HID report descriptor (read from the device)
--------------------------------------------
  FR1 FEATURE  7 data bytes   command + 4-byte SPI
  FR2 FEATURE  135 data bytes page buffer (not used for 4-byte SPI)
  FR3 FEATURE  127 data bytes page-read buffer
  FR4 FEATURE  15 data bytes  unused here

Command frames
--------------
FR1 is one command register: a SET loads it and the GET executes it and
returns the result, so two SETs in a row execute once, with the second
payload. Report id is always 0x01. Never pad to 136; never SET FR2 with
zeros -- that USB-resets the device.

  0x0F  identify     01 0F 01 00 00 00 02 00
  0x0D  connect      01 0D 00 01 20 A0 40 C0
                     01 0D 01 01 20 A0 40 C0   (target VCC + clock)
  0x0E  SPI xfer     01 0E b0 b1 b2 b3 00 04
  GET FR1 8 bytes    first 4 bytes are SPI RX; payload is byte [3]
  0x0B  disconnect   01 0B 01 00 00 00 00 00

0x0D byte1 is the RST level. Byte 2 reads as a target-VCC flag and is not
one: the VCC pin on this dongle is tied to USB 5 V and no frame gates it,
so holding that byte low changes nothing. There is therefore no way to
power-cycle a board from here, which matters for any
part whose bootloader is entered on power-on. The AT89S52 resets on
a HIGH level, so the whole programming session runs with byte1 = 1 and the
part held in reset; byte1 = 0 is the falling edge that starts user code.
0x0B is not that edge -- it tri-states the header, and the pull-up then
parks RST between the two AT89S52 thresholds, which neither resets nor runs
the part. `release_to_run` therefore ends a session with 0x0D, not 0x0B.

AT89S51/S52 serial-ISP
----------------------
  Enable  : TX AC 53 00 00  RX[3] == 0x69
  Erase   : TX AC 80 00 00  wait >= 510 ms
  Sig[i]  : TX 28 0i 00 00  RX[3] = signature byte i
  Rd byte : TX 20 hi lo 00  RX[3] = program memory, RX[1] echoes 0x20
  Wr byte : TX 40 hi lo data wait >= 1.5 ms
"""

from __future__ import annotations

import pathlib
import time

from ..progress import (Progress, Spinner, banner, complete, error,
                        info, note, stage)

_VID = 0x03EB
_PID = 0xC8B4
_ISP_ACK = 0x69
_ERASE_MS = 520
_WRITE_MS = 5
_FR1_LEN = 8
_AT89S52_SIG = (0x1E, 0x52, 0x06)


def _expected_signature(target: str) -> tuple[int, ...]:
    """The signature the catalog records for *target*, if it records one.

    Every AT89S part answers the same enable sequence and reports its own
    three bytes, so the check belongs to the catalog rather than to one
    part written into this module.
    """
    try:
        from .. import boards as boards_mod
    except ImportError:
        return ()
    for board in boards_mod.all_boards().values():
        if board.family != "mcs51" or board.part.lower() != target.lower():
            continue
        text = (board.signature or "").strip()
        if not text:
            return ()
        try:
            return tuple(int(byte, 16) for byte in text.split())
        except ValueError:
            return ()
    return ()

# 0x0D payload tails. The four clock bytes make the programmer drive XTAL1;
# a board with its own crystal must leave them at zero to run.
_CLOCK = (0x20, 0xA0, 0x40, 0xC0)
_NOCLK = (0x00, 0x00, 0x00, 0x00)


def _spi_rx(raw: list[int]) -> list[int]:
    """Pull 4 SPI RX bytes out of a Feature Report 1 GET.

    The device returns 8 bytes with no extra report-id prefix; hidapi on
    Windows may insert a leading 0x01. Trailing 0x60 0xFF bytes are stale
    SRAM.
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


def _bytes_to_program(data: dict[int, int]) -> dict[int, int]:
    """Drop the bytes a chip erase already left at 0xFF.

    Byte-at-a-time ISP costs about 5 ms per write, so padding an 8 KB part
    with 0xFF would spend most of a minute writing the erased value back.
    """
    return {addr: value for addr, value in data.items() if value != 0xFF}


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
        if len(devs) != 1:
            raise FileNotFoundError(
                f"expected exactly one USB-ISP programmer "
                f"(VID {_VID:04X} / PID {_PID:04X}), found {len(devs)}; "
                "refusing to power or reset an ambiguous target")
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

    def _fr1(self, payload7: list[int]) -> None:
        buf = bytes([0x01] + list(payload7[:7]))
        if len(buf) != _FR1_LEN:
            buf = (buf + bytes(_FR1_LEN))[:_FR1_LEN]
        self._dev.send_feature_report(buf)

    def _fr1_get(self) -> list[int]:
        raw = self._dev.get_feature_report(0x01, _FR1_LEN)
        return _spi_rx(list(raw) if raw else [])

    def _exec(self, payload7: list[int], settle_ms: float = 5) -> list[int]:
        """SET a command into FR1, then GET — which is what runs it.

        The dongle treats FR1 as one command register: a SET only loads it,
        and the GET is the trigger. Two SETs in a row therefore execute once,
        with the second payload. SET 40 hi lo data with no GET leaves the
        byte at 0xFF, and SET AC 80 00 00 with no GET does not erase however
        long you wait.
        """
        self._fr1(payload7)
        time.sleep(settle_ms / 1000)
        return self._fr1_get()

    def _spi_fire(self, b0: int, b1: int, b2: int, b3: int,
                  settle_ms: float = _WRITE_MS) -> None:
        """Run one SPI transaction and throw the reply away.

        Erase and byte-write have nothing to say on MISO, but the GET still
        has to happen — it is the execute trigger, not just a read.
        """
        self._exec([0x0E, b0, b1, b2, b3, 0x00, 0x04], settle_ms=settle_ms)

    def identify(self) -> None:
        try:
            self._exec([0x0F, 0x01, 0x00, 0x00, 0x00, 0x02, 0x00], settle_ms=20)
        except OSError:
            pass

    def connect(self, clock: bool = True) -> None:
        """Enable target VCC and hold AT89S52 RST high (programming level)."""
        tail = list(_CLOCK if clock else _NOCLK)
        self._exec([0x0D, 0x00, 0x01, *tail], settle_ms=20)
        self._exec([0x0D, 0x01, 0x01, *tail], settle_ms=50)
        self._connected = True

    def disconnect(self) -> None:
        """Tri-state the ISP header. Not a way to start user code."""
        self._exec([0x0B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00], settle_ms=20)
        self._connected = False

    def auto_reset(self, hold_ms: int = 60, settle_ms: int = 150) -> None:
        """Drive one RST high-to-low edge so the CPU fetches from 0x0000.

        AT89S52 RST is active HIGH and needs two machine cycles of it, so the
        falling edge is what ends reset. The clock bytes are zeroed first:
        otherwise the programmer keeps driving XTAL1 and fights the board
        crystal once the part is running.

        Both frames go through `_exec`. A bare SET only loads the command
        register, so a release sent that way never runs: RST stays at the
        programming level and the part never leaves reset.

        0x0B is deliberately absent. Tri-stating the header leaves RST on the
        programmer's pull-up, at a level inside the AT89S52 undefined band.
        """
        self._exec([0x0D, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00],
                   settle_ms=hold_ms)
        self._exec([0x0D, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00],
                   settle_ms=settle_ms)
        self._connected = False


    def release_to_run(self) -> None:
        """End an ISP session in user mode, with target VCC still supplied."""
        self.auto_reset()

    def spi(self, b0: int, b1: int, b2: int, b3: int,
            wait_ms: int = 5) -> list[int]:
        """Execute one 4-byte SPI transaction; return 4 RX bytes."""
        self._spi_fire(b0, b1, b2, b3)
        time.sleep(wait_ms / 1000)
        return self._fr1_get()

    def spi_echoed(self, b0: int, b1: int, b2: int, b3: int,
                   wait_ms: int = 5, retries: int = 4) -> list[int]:
        """`spi`, but only accept a frame whose RX[1] echoes the command.

        The target shifts each TX byte back out on MISO one byte later, so
        RX[1] is a check on the whole frame: when it is not the command the
        GET raced the transfer and RX[3] is some other transaction's data.
        """
        rx = [0, 0, 0, 0]
        for attempt in range(retries):
            rx = self.spi(b0, b1, b2, b3, wait_ms=wait_ms)
            if rx[1] == b0:
                return rx
            time.sleep(0.002 * (attempt + 1))
        return rx

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
            self.spi_echoed(0x28, 0, 0, 0)[3],
            self.spi_echoed(0x28, 1, 0, 0)[3],
            self.spi_echoed(0x28, 2, 0, 0)[3],
        )

    def read_lock_bits(self) -> int:
        """Byte 4 of the read-lock-bits frame; LB1..LB3 are bits 2..4."""
        return self.spi_echoed(0x24, 0x00, 0x00, 0x00)[3]

    def chip_erase(self, timeout_s: float = 12.0, spinner=None) -> None:
        """Erase, then wait until the array really reads blank.

        The datasheet puts tERASE at 500 ms. Parts routinely need several
        times that, and a short erase does not merely leave a few bytes behind —
        every byte keeps its high nibble, and repeating the short erase never
        finishes the job. So the wait grows until a sample of the array is
        0xFF, instead of trusting one fixed delay.
        """
        wait = _ERASE_MS / 1000
        deadline = time.monotonic() + timeout_s
        while True:
            for _ in range(2):
                self._spi_fire(0xAC, 0x80, 0x00, 0x00, settle_ms=5)
                spent = 0.0
                while spent < wait:
                    time.sleep(min(0.1, wait - spent))
                    spent += 0.1
                    if spinner is not None:
                        spinner.tick()
            # Erase drops programming-enable; pulse RST and send AC 53 again.
            self.enter_isp()
            if self.blank_check(samples=8) is None:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"chip erase did not blank the array within {timeout_s:.0f} s")
            wait = min(wait * 2.5, 4.0)

    def read_byte(self, addr: int) -> int:
        return self.spi_echoed(0x20, addr >> 8, addr & 0xFF, 0x00)[3]

    def read_block(self, addr: int, length: int) -> list[int]:
        return [self.read_byte(addr + i) for i in range(length)]

    def blank_check(self, code_size: int = 8192,
                    samples: int = 64) -> int | None:
        """First sampled address chip erase did not leave at 0xFF, else None."""
        step = max(1, code_size // samples)
        for addr in range(0, code_size, step):
            if self.read_byte(addr) != 0xFF:
                return addr
        return None

    def write_byte(self, addr: int, data: int) -> None:
        self._spi_fire(0x40, addr >> 8, addr & 0xFF, data)
        time.sleep(_WRITE_MS / 1000)
        if data == 0xFF:
            return
        for _ in range(20):
            if self.read_byte(addr) == data:
                return
            time.sleep(0.001)

    def write_image(self, data: dict[int, int], on_byte=None) -> int:
        payload = _bytes_to_program(data)
        for addr in sorted(payload):
            self.write_byte(addr, payload[addr])
            if on_byte is not None:
                on_byte()
        return len(payload)

    def verify_image(self, data: dict[int, int],
                     on_byte=None) -> list[tuple[int, int, int]]:
        """[(addr, expected, actual)] for every byte that did not match."""
        bad: list[tuple[int, int, int]] = []
        for addr, expected in sorted(data.items()):
            actual = self.read_byte(addr)
            if actual != expected:
                bad.append((addr, expected, actual))
            if on_byte is not None:
                on_byte()
        return bad


def _programmer_or_report() -> _Programmer | int:
    try:
        return _Programmer()
    except ImportError as exc:
        print(f"error: {exc}")
        return 1


def probe(target: str) -> int:
    """Open the programmer, try ISP enable, print the signature. No erase."""
    prog = _programmer_or_report()
    if isinstance(prog, int):
        return prog
    try:
        with prog:
            try:
                prog.enter_isp()
            except RuntimeError as exc:
                error(str(exc), title="ISP enable failed")
                return 1
            sig = prog.read_signature()
            sig_text = " ".join(f"{b:02X}" for b in sig)
            expected = _expected_signature(target)
            if expected and sig == expected:
                info(f"found {target.upper()}, signature {sig_text}")
            else:
                info(f"signature {sig_text}")
                if expected:
                    want = " ".join(f"{b:02X}" for b in expected)
                    info(f"warning: {target.upper()} should report {want}")
            prog.release_to_run()
    except FileNotFoundError as exc:
        error(str(exc), title="programmer not found")
        return 1
    except OSError as exc:
        error(f"HID I/O failed: {exc}", title="programmer stopped responding")
        return 1
    return 0


def reset(target: str) -> int:
    """Pulse RST and leave the part running. No erase, no ISP session left."""
    prog = _programmer_or_report()
    if isinstance(prog, int):
        return prog
    try:
        with prog:
            prog.auto_reset()
    except FileNotFoundError as exc:
        error(str(exc), title="programmer not found")
        return 1
    except OSError as exc:
        error(f"HID I/O failed: {exc}", title="reset failed")
        return 1
    info(f"reset  {target} released from reset")
    return 0


def flash(image: pathlib.Path, target: str, run: bool = True) -> int:
    """Erase, program and verify *image* (.ihx). Returns 0 on success.

    With *run* false the part is left held in reset, so a caller can attach
    to its UART before the first instruction executes. That startup output
    is otherwise gone by the time a serial port finishes opening.
    """
    banner(f"8051 Flash Console - Target: {target}")

    prog = _programmer_or_report()
    if isinstance(prog, int):
        return prog

    try:
        with prog:
            stage(0, "Connecting", f"USB-ISP {_VID:04X}:{_PID:04X}")
            try:
                prog.enter_isp()
            except RuntimeError as exc:
                error(str(exc), title="ISP enable failed",
                      hints=("check the IDC10 pin-1 alignment against "
                             "docs/wiring/usbasp-idc10.md",
                             "confirm the board is powered and its crystal "
                             "is running",
                             "an STC part in the same socket uses the UART "
                             "bootloader, not this header"))
                return 1

            sig = prog.read_signature()
            sig_text = " ".join(f"{b:02X}" for b in sig)
            expected = _expected_signature(target)
            if expected and sig != expected:
                want = " ".join(f"{b:02X}" for b in expected)
                error(f"signature {sig_text} is not {target.upper()} ({want})",
                      title="wrong part in the socket",
                      hints=("nothing was erased",
                             "select the board that matches the part, or "
                             "fit the part that matches the board"))
                return 1
            stage(5, "Connected", f"signature {sig_text}")

            data = _parse_ihx(image)
            if not data:
                error(f"{image.name} is empty or not valid Intel HEX",
                      title="nothing to program",
                      hints=("did Verify succeed?",))
                return 1
            payload = _bytes_to_program(data)

            with Spinner("Erasing") as spin:
                prog.chip_erase(spinner=spin)
                dirty = prog.blank_check()
                if dirty is not None:
                    spin.fail(f"0x{dirty:04X} still programmed")
                    error(f"the array still holds data at 0x{dirty:04X} "
                          "after a chip erase",
                          title="erase did not finish",
                          hints=("the part may be lock-bit protected",
                                 "check VCC is steady under the "
                                 "programmer's load"))
                    return 1

            with Progress("Programming", len(payload)) as bar:
                prog.write_image(data, on_byte=bar.step)

            # The first reads after the last write can still catch that write
            # cycle; throw them away before the verify pass counts errors.
            for _ in range(3):
                prog.read_byte(0x0000)

            with Progress("Verifying", len(data)) as bar:
                bad = prog.verify_image(data, on_byte=bar.step)
            if bad:
                trace = tuple(
                    f"0x{addr:04X}: wrote 0x{want:02X}, read 0x{got:02X}"
                    for addr, want, got in bad[:8]
                )
                error(f"{len(bad)} byte(s) did not read back as written",
                      title="verify failed",
                      hints=("the image on the part is not the one built",
                             "check the ISP cable and the supply before "
                             "trusting the board"),
                      details=trace)
                return 1

            if not run:
                complete("Programmed, held in reset",
                         "Reset             : held - waiting for the caller "
                         "to release it")
                return 0
            prog.release_to_run()
            complete(
                "Upload complete",
                "Reset             : released - board running the new firmware",
                "Power             : VCC still supplied by the programmer",
            )
            note("nothing on the UART? check EA (pin 31) is tied to VCC: "
                 "with EA low the CPU fetches from external memory and never "
                 "runs the flash just verified")
    except FileNotFoundError as exc:
        error(str(exc), title="programmer not found",
              hints=("install the driver as HidUsb, not WinUSB",
                     "run `python -m niusburner setup` to check"))
        return 1
    except OSError as exc:
        error(f"HID I/O failed: {exc}", title="programmer stopped responding",
              hints=("unplug and replug the dongle, then retry",))
        return 1
    return 0
