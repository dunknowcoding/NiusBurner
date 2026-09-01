"""STC serial-bootloader backend, driven through stcgal.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

An STC89C52RC sits in the same DIP-40 socket as an AT89S52 and runs the same
instruction set, but it has no SPI programming interface at all. The ISP
header cannot reach it: the part is written through its own
UART bootloader, which is a different protocol on different pins.

That bootloader only listens for a short window immediately after reset, and
the STC89 generation has no software entry into it -- the chip has to be
power-cycled while the host is already sending the sync pattern. So a flash
here is a two-party operation: this module talks, and the board's power
has to be interrupted. `stcgal` handles the protocol; this module handles
locating it, framing the request, and saying clearly what the operator has
to do.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import time

from ..progress import (banner, complete, error, info, note, stage,
                        waited, waiting)

#: stcgal's name for the protocol each family speaks.
PROTOCOLS = {
    "stc89": "stc89",
    "stc12": "stc12",
    "stc15": "stc15",
    "stc8": "stc8",
    "stc8d": "stc8d",
    "stc8g": "stc8g",
}

DEFAULT_BAUD = 19200


def _protocol(target: str) -> str:
    """The bootloader generation *target* speaks, per the catalog.

    The generations are not interchangeable, so this must follow the part
    rather than assume the one this module was written against.
    """
    try:
        from .. import boards as boards_mod
    except ImportError:
        return PROTOCOLS["stc89"]
    for board in boards_mod.all_boards().values():
        if board.part.lower() == target.lower():
            return PROTOCOLS.get(board.protocol, PROTOCOLS["stc89"])
    return PROTOCOLS["stc89"]

#: How the board's power is interrupted, when something can do it.
#:
#: An STC89 enters its bootloader on power-on and on nothing else: there is
#: no pin to assert and no way in from software. So an upload that nobody
#: has to touch needs VDD under electrical control, which is what every
#: commercial STC development board does -- a P-channel MOSFET or a PNP in
#: the supply, driven by the serial adapter's DTR or RTS line.
#:
#: "dtr" and "rts" name that line. "off" means nobody can, and the console
#: asks a person to do it.
#:
#: The ISP header cannot: its 0x0D frame carries a VCC byte, and setting it
#: low does not gate the rail.
#: The printing continued straight through a 1.5 s cut, so that byte does
#: not gate the rail whatever else it does.
RESET_PINS = ("dtr", "rts")

#: The bootloader answers at a low rate and is then handed a faster one.
HANDSHAKE_BAUD = 2400
#: stcgal keeps pulsing until the bootloader answers, and the answer only
#: comes after a power-on. The deadline has to outlast a few cycle attempts
#: plus a person reaching for a switch when the automatic route is off.
PROCESS_TIMEOUT_SECONDS = 300


def serial_identity(port: str) -> tuple[str, int | None, int | None, str, str, str]:
    """Capture one exact UART endpoint without opening or resetting it."""
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("pyserial is required for the STC UART") from exc
    wanted = port.strip().upper().rstrip(":")
    matches = [item for item in list_ports.comports()
               if str(item.device).upper().rstrip(":") == wanted]
    if len(matches) != 1:
        raise RuntimeError(f"expected exact UART {wanted} once, found {len(matches)}")
    item = matches[0]
    return (
        str(item.device).upper().rstrip(":"), item.vid, item.pid,
        str(item.serial_number or ""), str(item.location or ""),
        str(item.hwid or "").upper(),
    )


def _run_guarded(command: list[str], port: str) -> subprocess.CompletedProcess[str]:
    """Run stcgal under a deadline and require the same UART afterwards."""
    before = serial_identity(port)
    primary: Exception | None = None
    done = None
    try:
        done = subprocess.run(
            command, capture_output=True, text=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        primary = exc
    try:
        after = serial_identity(port)
        if after != before:
            raise RuntimeError(
                f"UART identity changed from {before!r} to {after!r}")
    except Exception as endpoint_error:
        if primary is not None:
            raise RuntimeError(
                f"stcgal failed ({primary}); UART restoration also failed "
                f"({endpoint_error})"
            ) from endpoint_error
        raise RuntimeError(
            f"exact UART did not remain restored: {endpoint_error}"
        ) from endpoint_error
    if primary is not None:
        raise primary
    assert done is not None
    return done


#: Why a bootloader stays silent, in the order worth checking. The first is
#: the one that costs an afternoon: if the serial adapter and the programmer
#: both feed VCC, neither can take it away on its own, so no amount of
#: cutting power at one of them produces a power-on reset. Unplugging the
#: adapter by hand does not help either -- that closes the port being
#: programmed through.
_WHY_NO_ANSWER = (
    "is anything else feeding VCC? Two supplies tied together cannot be "
    "interrupted at one of them, so neither produces a power-on",
    "nothing here switches VDD on its own: the ISP header cannot, and a "
    "person or a DTR/RTS supply switch has to",
    "an STC89 enters its bootloader on power-on only; a reset pulse will "
    "not do it, and there is no way in from software",
    "check TX/RX are crossed and share a ground",
    "an STC part cannot be reached through the ISP header at all",
)


#: The sequence a sketch built with NIUS_ISP_ENTRY watches for. Long and
#: implausible on purpose: a sketch that received it by accident would
#: reset into the bootloader, which is a bad surprise. Must match MAGIC[]
#: in adapters/Arduino/mcs51/nius_ispentry.c byte for byte.
ENTRY_MAGIC = bytes([
    ord("N"), ord("B"), 0x1B, ord("I"), ord("S"), ord("P"), 0x1B,
    ord("E"), ord("N"), ord("T"), ord("R"), ord("Y"), 0x1B,
    0xA5, 0x5A, 0xA5, 0x5A,
])


def ask_for_bootloader(port: str, baud: int = 9600) -> bool:
    """Ask a running sketch to reset itself into the bootloader.

    An STC89 has no pin and no supply switch that software can reach here,
    but ISP_CONTR lets the part reset itself into the ISP block. A sketch
    built with bootloader entry watches the UART for this sequence and does
    exactly that, which turns an upload that needed a hand on the power
    into one that does not.

    Returns False only when the port cannot be opened; a part that is not
    listening simply ignores the bytes, and the caller falls through to
    asking a person.
    """
    try:
        import serial
    except ImportError:
        return False
    try:
        with serial.Serial(port=port, baudrate=baud, timeout=0.2) as ser:
            ser.reset_input_buffer()
            ser.write(ENTRY_MAGIC)
            ser.flush()
    except Exception:
        return False
    # The part resets and its bootloader starts listening; give it that long
    # before the handshake begins.
    time.sleep(0.05)
    return True


#: The copy carried in this package, so an upload works from a clean
#: checkout rather than failing on a machine that never had one installed.
VENDORED = "niusburner.vendor.stcgal"


def find_stcgal() -> list[str] | None:
    """How to run stcgal, or None.

    The vendored copy wins. It is the version this package was tested
    against, and it carries a fix the installed one may not: upstream
    picks the STC8 calibration exchange by the requested trim frequency
    rather than by the part, which makes every STC8G and STC8H upload fail
    with a timeout that looks like a wiring fault.

    An installed stcgal is still accepted, so a machine that has one is
    not broken by this, and a stcgal on PATH after that.
    """
    try:
        import importlib.util

        if importlib.util.find_spec(VENDORED) is not None:
            return [sys.executable, "-m", VENDORED]
    except (ImportError, ValueError):
        pass
    try:
        import stcgal  # noqa: F401
    except ImportError:
        pass
    else:
        return [sys.executable, "-m", "stcgal"]
    found = shutil.which("stcgal")
    return [found] if found else None


def version() -> str | None:
    """Which stcgal will actually run, and where it came from."""
    try:
        from ..vendor.stcgal import __version__ as vendored

        return f"{vendored} (vendored)"
    except Exception:
        pass
    try:
        import importlib.metadata as md

        return md.version("stcgal")
    except Exception:
        return None


def autoreset_args(reset_pin: str) -> list[str]:
    """stcgal's flags for cycling power from a modem control line.

    -r is not used: that runs a shell command, and a command cannot switch
    a rail that needs a switch on it. -A names the pin, and -a is what
    makes stcgal consult it at all -- passing -A alone looks right and
    silently does nothing.
    """
    pin = (reset_pin or "").strip().lower()
    if pin not in RESET_PINS:
        return []
    return ["-a", "-A", pin]


def _missing() -> int:
    error(
        "stcgal is not installed on this interpreter",
        title="no STC bootloader tool",
        hints=("python -m pip install stcgal",
               "an STC part is written through its UART, not the ISP header"))
    return 1


def probe(target: str, port: str, baud: int = DEFAULT_BAUD,
          reset_pin: str = "", soft_entry: bool = True,
          sketch_baud: int = 9600) -> int:
    """Ask the bootloader to identify itself.

    With *reset_pin* set to dtr or rts, the adapter switches VDD and this
    is one command with nobody touching anything. Without it, a person has
    to interrupt power, and the console says so.
    """
    tool = find_stcgal()
    if tool is None:
        return _missing()
    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {HANDSHAKE_BAUD} baud")
    cycle = autoreset_args(reset_pin)
    if cycle:
        info(f"cycling target power from {reset_pin.upper()}")
    elif soft_entry and ask_for_bootloader(port, sketch_baud):
        info("asking the running sketch to reset into its bootloader")
    else:
        info("power-cycle the board now, and hold it off for a moment: the "
             "bootloader is entered on power-on only")
        info("the surest order is to remove power first, start this, then "
             "restore it -- the listening window is short and opens once")
    cmd = tool + ["-P", _protocol(target), "-p", port,
                  "-b", str(baud), "-l", str(HANDSHAKE_BAUD), "-D"]
    cmd += cycle
    note(" ".join(cmd))
    try:
        done = _run_guarded(cmd, port)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error(str(exc)[:400], title="STC probe transport failed",
              hints=(f"confirm {port} is still the exact CH341 endpoint",))
        return 1
    if done.returncode != 0:
        error((done.stderr or done.stdout).strip()[:400],
              title="the bootloader did not answer",
              hints=_WHY_NO_ANSWER + (
                  f"confirm {port} is the adapter wired to this part",))
        return 1
    for line in done.stdout.splitlines():
        if line.strip():
            info(line.strip())
    return 0


#: Families programmed here rather than through stcgal. Those bootloaders
#: are not asked to trim their oscillator first, which is the step they do
#: not answer and the reason the general-purpose route cannot write a byte
#: to them.
NATIVE_PROTOCOLS = ("stc8g", "stc8d")


def _flash_stc8(image: pathlib.Path, target: str, port: str, protocol: str,
                soft_entry: bool, sketch_baud: int) -> int:
    """Program an STC8G/STC8H part directly."""
    from . import stc8_isp

    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {stc8_isp.HANDSHAKE_BAUD} baud")
    info(f"{protocol}: programming without retrimming the oscillator")
    if soft_entry:
        ask_for_bootloader(port, sketch_baud)
    info("power-cycle the board now: the bootloader is entered on power-on "
         "only, and this is already listening for it")

    try:
        from ..vendor.stcgal.ihex import IHex

        with image.open("rb") as handle:
            payload = IHex.read(handle).extract_data()
    except (OSError, ValueError) as exc:
        error(str(exc)[:400], title="the image could not be read",
              hints=("the file should be Intel HEX from a NiusBurner build",))
        return 1

    try:
        # info and stage, not note: note is silent unless the verbose
        # environment variable is set, and this is the one part of an
        # upload that stands still for a minute waiting for a person. It
        # has to say so in the IDE panel, where nobody has set anything.
        def tick(left):
            if left is None:
                waited()
            else:
                waiting("Waiting", "%ds left" % int(left))

        stc8_isp.program(port, payload, announce=info, progress=stage,
                         tick=tick)
    except stc8_isp.Stc8Error as exc:
        error(str(exc)[:400], title="programming failed",
              hints=_WHY_NO_ANSWER)
        return 1
    except OSError as exc:
        error(str(exc)[:400], title="STC upload transport failed",
              hints=(f"confirm {port} is still the exact adapter endpoint",))
        return 1

    complete("Upload complete",
             "Oscillator        : left as it was; the sketch runs at the "
             "catalog frequency",
             "Power             : supplied by the board, not the programmer")
    return 0


def flash(image: pathlib.Path, target: str, port: str,
          baud: int = DEFAULT_BAUD, run: bool = True,
          reset_pin: str = "", soft_entry: bool = True,
          sketch_baud: int = 9600) -> int:
    """Program *image* through the STC bootloader.

    With *reset_pin* set to dtr or rts, the adapter switches VDD and this
    is one command with nobody touching anything. Without it, a person has
    to interrupt power, and the console says so.
    """
    if not image.is_file():
        error(f"image not found: {image}", title="nothing to program",
              hints=("did Verify succeed?",))
        return 1

    protocol = _protocol(target)
    if protocol in NATIVE_PROTOCOLS:
        return _flash_stc8(image, target, port, protocol, soft_entry,
                           sketch_baud)

    tool = find_stcgal()
    if tool is None:
        return _missing()

    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {HANDSHAKE_BAUD} baud")
    cycle = autoreset_args(reset_pin)
    if cycle:
        info(f"cycling target power from {reset_pin.upper()}")
    elif soft_entry and ask_for_bootloader(port, sketch_baud):
        info("asking the running sketch to reset into its bootloader")
    else:
        info("power-cycle the board now, and hold it off for a moment: the "
             "bootloader is entered on power-on only")
        info("the surest order is to remove power first, start this, then "
             "restore it -- the listening window is short and opens once")
    cmd = tool + ["-P", _protocol(target), "-p", port,
                  "-b", str(baud), "-l", str(HANDSHAKE_BAUD)]
    cmd += cycle
    cmd += [str(image)]
    note(" ".join(cmd))
    try:
        done = _run_guarded(cmd, port)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error(str(exc)[:400], title="STC upload transport failed",
              hints=(f"confirm {port} is still the exact CH341 endpoint",))
        return 1
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        error(output.strip()[:400] or "stcgal reported a failure",
              title="programming failed",
              hints=_WHY_NO_ANSWER)
        return 1
    for line in output.splitlines():
        if line.strip():
            note(line.strip())
    complete("Upload complete",
             "Reset             : the bootloader starts the new firmware "
             "itself",
             "Power             : supplied by the board, not the programmer")
    return 0
