"""STC serial-bootloader backend, driven through stcgal.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

An STC89C52RC sits in the same DIP-40 socket as an AT89S52 and runs the same
instruction set, but it has no SPI programming interface at all. The ISP
header on this bench cannot reach it: the part is written through its own
UART bootloader, which is a different protocol on different pins.

That bootloader only listens for a short window immediately after reset, and
the STC89 generation has no software entry into it -- the chip has to be
power-cycled while the host is already sending the sync pattern. So a flash
here is a two-party operation: this module talks, and somebody has to switch
the board's power. `stcgal` handles the protocol; this module handles
locating it, framing the request, and saying clearly what the operator has
to do.

Nothing here is on silicon yet. No STC part has been in the socket on this
bench, so the status stays `implemented`: the plumbing is exercised against
stcgal's own protocol classes, not against a chip.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

from ..progress import banner, complete, error, info, note, stage

#: stcgal's name for the protocol each family speaks.
PROTOCOLS = {
    "stc89": "stc89",
    "stc12": "stc12",
    "stc15": "stc15",
    "stc8": "stc8",
}

DEFAULT_BAUD = 19200
#: The bootloader answers at a low rate and is then handed a faster one.
HANDSHAKE_BAUD = 2400


def find_stcgal() -> list[str] | None:
    """How to run stcgal on this machine, or None.

    The module on this interpreter wins over a stcgal on PATH, because it is
    the one whose version can be reported.
    """
    try:
        import stcgal  # noqa: F401
    except ImportError:
        pass
    else:
        return [sys.executable, "-m", "stcgal"]
    found = shutil.which("stcgal")
    return [found] if found else None


def version() -> str | None:
    try:
        import importlib.metadata as md

        return md.version("stcgal")
    except Exception:
        return None


def _missing() -> int:
    error(
        "stcgal is not installed on this interpreter",
        title="no STC bootloader tool",
        hints=("python -m pip install stcgal",
               "an STC part is written through its UART, not the ISP header"))
    return 1


def probe(target: str, port: str, baud: int = DEFAULT_BAUD) -> int:
    """Ask the bootloader to identify itself. Needs a power cycle."""
    tool = find_stcgal()
    if tool is None:
        return _missing()
    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {HANDSHAKE_BAUD} baud")
    info("power-cycle the board now: the STC bootloader only listens in the "
         "first moments after reset")
    cmd = tool + ["-P", PROTOCOLS["stc89"], "-p", port,
                  "-b", str(baud), "-l", str(HANDSHAKE_BAUD), "-D"]
    note(" ".join(cmd))
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        error((done.stderr or done.stdout).strip()[:400],
              title="the bootloader did not answer",
              hints=("power-cycle the board while this is running",
                     "check TX/RX are crossed and share a ground",
                     f"confirm {port} is the adapter wired to this part"))
        return 1
    for line in done.stdout.splitlines():
        if line.strip():
            info(line.strip())
    return 0


def flash(image: pathlib.Path, target: str, port: str,
          baud: int = DEFAULT_BAUD, run: bool = True) -> int:
    """Program *image* through the STC bootloader. Needs a power cycle."""
    tool = find_stcgal()
    if tool is None:
        return _missing()
    if not image.is_file():
        error(f"image not found: {image}", title="nothing to program",
              hints=("did Verify succeed?",))
        return 1

    banner(f"8051 Flash Console - Target: {target}")
    stage(0, "Waiting", f"{port} at {HANDSHAKE_BAUD} baud")
    info("power-cycle the board now: the STC bootloader only listens in the "
         "first moments after reset")
    cmd = tool + ["-P", PROTOCOLS["stc89"], "-p", port,
                  "-b", str(baud), "-l", str(HANDSHAKE_BAUD), str(image)]
    note(" ".join(cmd))
    done = subprocess.run(cmd, capture_output=True, text=True)
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        error(output.strip()[:400] or "stcgal reported a failure",
              title="programming failed",
              hints=("power-cycle the board while this is running",
                     "check TX/RX are crossed and share a ground",
                     "an STC part cannot be reached through the ISP header"))
        return 1
    for line in output.splitlines():
        if line.strip():
            note(line.strip())
    complete("Upload complete",
             "Reset             : the bootloader starts the new firmware "
             "itself",
             "Power             : supplied by the board, not the programmer")
    return 0
