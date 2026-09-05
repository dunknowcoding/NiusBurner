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
import re
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

#: How long to keep retrying a failed attempt. The tool itself makes one
#: and gives up; on a board powered through a hand-operated switch that is
#: not enough, and a second attempt costs only another power cycle.
RETRY_BUDGET_SECONDS = 180.0


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


#: What the tool prints, and where each phrase belongs in the house
#: progress. stcgal writes its own running commentary, which is fine on a
#: terminal and is not what an upload looks like everywhere else in this
#: package -- and, being another program's stdout, it arrives whenever it
#: arrives rather than when there is something to say.
_STCGAL_STAGES = (
    ("waiting for mcu", 0, "Waiting for handshake",
     "switch the board's supply off and on"),
    ("target model", 10, "Handshake", ""),
    ("switching to", 20, "Link", ""),
    ("erasing", 30, "Erasing", ""),
    ("writing flash", 40, "Programming", ""),
    ("finishing write", 95, "Finishing", "committing the last block"),
    ("setting options", 97, "Options", ""),
)

#: The tool draws its own progress bar. Nesting one inside this package's
#: is unreadable -- and its block characters arrive as mojibake in a
#: console that is not UTF-8 -- so the number is taken and the bar is
#: redrawn here. Writing is the span from the erase to the finish.
_WRITE_PERCENT = re.compile(r"writing flash:\s*(\d+)%")
_WRITE_FROM, _WRITE_TO = 40, 94


#: The furthest the bar has got in this attempt. The tool ends its write
#: with a summary line carrying no percentage, which falls through to the
#: general case and would otherwise send the bar backwards from 94 to 40 --
#: and a bar that retreats is a lie about progress. Reset per attempt,
#: because a retry really does start again.
_furthest = 0


def _restart_bar() -> None:
    global _furthest
    _furthest = 0


def _advance(percent: int, label: str, detail: str) -> None:
    """Draw a stage, never behind one already drawn."""
    global _furthest
    _furthest = max(_furthest, percent)
    stage(_furthest, label, detail)


def _restyle(line: str) -> None:
    """Show one line of the tool's output the way this package shows things.

    Everything is shown, because an upload that stands still waiting for
    somebody to switch a supply has to look alive in an IDE panel, and the
    lines that say so come from the tool rather than from here. The ones
    that name a stage also move the bar; the rest are printed as they are.
    """
    text = line.strip()
    if not text:
        return
    lowered = text.lower()
    written = _WRITE_PERCENT.search(lowered)
    if written:
        share = min(100, max(0, int(written.group(1))))
        _advance(_WRITE_FROM + (_WRITE_TO - _WRITE_FROM) * share // 100,
                 "Programming", "%d%% of the image" % share)
        return
    for needle, percent, label, detail in _STCGAL_STAGES:
        if needle in lowered:
            _advance(percent, label, detail or text.rstrip(":. "))
            return
    info(text)


def _stream_guarded(command: list[str], port: str) -> int:
    """Run the tool, restyling its output as it arrives, under the guard.

    Not capture-and-replay: the wait for a power-on is most of a first
    upload, and a panel that prints nothing until it is over cannot be told
    from one that has hung. Output is read in small pieces rather than by
    line, because the tool marks progress with carriage returns and a line
    that never ends in a newline would never be shown.
    """
    _restart_bar()
    before = serial_identity(port)
    proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            errors="replace", bufsize=1)
    pending = ""
    deadline = time.monotonic() + PROCESS_TIMEOUT_SECONDS
    try:
        while True:
            piece = proc.stdout.read(1)
            if piece == "":
                break
            if piece in "\r\n":
                _restyle(pending)
                pending = ""
            else:
                pending += piece
            if time.monotonic() > deadline:
                proc.kill()
                raise subprocess.TimeoutExpired(command,
                                                PROCESS_TIMEOUT_SECONDS)
        _restyle(pending)
    finally:
        proc.stdout.close()
        proc.wait()
    after = serial_identity(port)
    if after != before:
        raise RuntimeError(
            f"UART identity changed from {before!r} to {after!r}")
    return proc.returncode


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
    protocol = _protocol(target)
    if protocol in NATIVE_PROTOCOLS:
        # The same routing flash() uses. These parts have a native handler
        # precisely because stcgal could not hold their handshake, so
        # probing them through stcgal asks the one transport already known
        # not to answer -- and then reports it as a silent board.
        return _probe_stc8(target, port, soft_entry, sketch_baud)
    tool = find_stcgal()
    if tool is None:
        return _missing()
    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {HANDSHAKE_BAUD} baud")
    cycle = autoreset_args(reset_pin)
    if cycle:
        info(f"cycling target power from {reset_pin.upper()}")
    else:
        if soft_entry:
            ask_for_bootloader(port, sketch_baud)
            # Asked, not achieved. Writing the request says nothing about
            # whether anything received it: a part with no sketch on it, or
            # one built without the watcher, ignores it silently. Claiming
            # success here also suppressed the instruction that is actually
            # needed, which is the one below.
            info("asked any running sketch to reset itself into the "
                 "bootloader; if none does, the supply is the way in")
        info("power-cycle the board now, and hold it off for a moment: the "
             "bootloader is entered on power-on only")
    # No image argument: stcgal then connects, reports what answered, and
    # exits, which is exactly what a probe is. Nothing else belongs here --
    # an option this build of stcgal does not have makes it exit on argument
    # parsing, long before the port is opened, and the failure then reads as
    # a silent bootloader.
    cmd = tool + ["-P", _protocol(target), "-p", port,
                  "-b", str(baud), "-l", str(HANDSHAKE_BAUD)]
    cmd += cycle
    note(" ".join(cmd))
    try:
        done = _run_guarded(cmd, port)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error(str(exc)[:400], title="STC probe transport failed",
              hints=(f"confirm {port} is still the exact CH341 endpoint",))
        return 1
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip()
        if said.startswith("usage:"):
            # An argument error, not a silent part. Saying "the bootloader
            # did not answer" here sends the reader to the wiring for a
            # fault that never reached the wire.
            error(said[:400],
                  title="stcgal rejected its own arguments",
                  hints=("this is a fault in the command built above, not "
                         "in the board or its wiring",))
            return 1
        error(said[:400],
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
NATIVE_PROTOCOLS = ("stc8g", "stc8d", "stc15")
#: Which of those have been run against a part. The rest are the same
#: exchange with one constant changed, which is well founded and is not
#: the same as having been seen to work.
CONFIRMED_PROTOCOLS = ("stc8g",)


def _probe_stc8(target: str, port: str, soft_entry: bool,
                sketch_baud: int) -> int:
    """Identify an STC8G/STC8H/STC15 part through the native handler."""
    from . import stc8_isp

    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {stc8_isp.HANDSHAKE_BAUD} baud")
    if soft_entry:
        ask_for_bootloader(port, sketch_baud)
    info("power-cycle the board now: the bootloader is entered on power-on "
         "only, and this is already listening for it")

    def tick(left):
        if left is None:
            waited()
        else:
            waiting("Waiting for handshake", "%ds left" % int(left))

    try:
        status = stc8_isp.identify(
            port, announce=info, progress=stage, tick=tick,
            expect_part=target)
    except stc8_isp.Stc8Error as exc:
        error(str(exc)[:400], title="the bootloader did not answer",
              hints=("is anything else feeding VCC? Two supplies tied "
                     "together cannot be interrupted at one of them",
                     f"confirm {port} is the adapter wired to this part"))
        return 1
    except (OSError, RuntimeError) as exc:
        error(str(exc)[:400], title="STC probe transport failed",
              hints=(f"confirm {port} is still the exact CH341 endpoint",))
        return 1
    info(f"part      {stc8_isp.part_name(status)}")
    stage(100, "Identified", stc8_isp.part_name(status))
    info("left the bootloader; the part is running its own firmware again")
    return 0


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
                waiting("Waiting for handshake", "%ds left" % int(left))

        if protocol not in CONFIRMED_PROTOCOLS:
            info(f"{protocol}: this exchange has not been run against a part "
                 "of this generation; it differs from the confirmed one by "
                 "the wait-state byte alone")
        stc8_isp.program(port, payload, announce=info, progress=stage,
                         tick=tick, expect_part=target, protocol=protocol)
    except stc8_isp.Stc8Error as exc:
        error(str(exc)[:400], title="programming failed",
              hints=_WHY_NO_ANSWER)
        return 1
    except OSError as exc:
        error(str(exc)[:400], title="STC upload transport failed",
              hints=(f"confirm {port} is still the exact adapter endpoint",))
        return 1

    complete("Upload complete",
             "Reset             : the bootloader starts the new firmware "
             "itself",
             "Power             : supplied by the board, not the programmer",
             "Oscillator        : left as it was; the sketch runs at the "
             "catalog frequency")
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
    else:
        if soft_entry:
            ask_for_bootloader(port, sketch_baud)
            # Asked, not achieved. Writing the request says nothing about
            # whether anything received it: a part with no sketch on it, or
            # one built without the watcher, ignores it silently. Claiming
            # success here also suppressed the instruction that is actually
            # needed, which is the one below.
            info("asked any running sketch to reset itself into the "
                 "bootloader; if none does, the supply is the way in")
        info("power-cycle the board now, and hold it off for a moment: the "
             "bootloader is entered on power-on only")
    cmd = tool + ["-P", _protocol(target), "-p", port,
                  "-b", str(baud), "-l", str(HANDSHAKE_BAUD)]
    cmd += cycle
    cmd += [str(image)]
    note(" ".join(cmd))
    # Retry, for as long as the budget allows.
    #
    # The tool makes one attempt and gives up, which is not enough on a
    # board whose supply is a switch under somebody's hand: a flick during
    # the exchange ends the session, and so does a rate change that happens
    # to time out. Both were seen here on a board that programmed perfectly
    # on the next attempt. Retrying is safe because the tool erases before
    # it writes, so every attempt starts from the same place.
    deadline = time.monotonic() + RETRY_BUDGET_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            code = _stream_guarded(cmd, port)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error(str(exc)[:400], title="STC upload transport failed",
                  hints=(f"confirm {port} is still the exact CH341 endpoint",))
            return 1
        if code == 0:
            break
        if time.monotonic() >= deadline:
            error("the programming tool reported a failure; its output is "
                  "above", title="programming failed", hints=_WHY_NO_ANSWER)
            return 1
        stage(0, "Restarting", "power the board off and on again")
        info("that attempt did not finish; nothing is lost, because the "
             "next one erases before it writes. Switch the supply off and "
             "on again when ready")
    complete("Upload complete",
             "Reset             : the bootloader starts the new firmware "
             "itself",
             "Power             : supplied by the board, not the programmer")
    return 0
