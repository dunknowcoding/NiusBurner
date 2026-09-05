"""PICkit 3 backend, driven through MPLAB's ipecmd.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

A PICkit 3 in its normal firmware is a USB HID device (04D8:900A), not a
serial port, and it speaks a protocol that only Microchip's own tooling
implements. `ipecmd` is that tooling's command line, and it ships inside
MPLAB X, so this module locates it, builds the request, and turns its
output into the same console every other target uses.

The options that matter here, from `ipecmd /?`:

    -TPPK3          select by PICkit 3 type when no exact serial is supplied
    -TS<serial>     select one exact programming tool by USB serial
    -P<part>        the part, without a leading PIC
    -F<file>        the HEX to program
    -M              program the device
    -Y              verify it afterwards
    -E              erase first
    -OL             release from reset when finished, instead of holding it
    -W              power the target from the tool

`-W` is deliberately not the default. Most target boards have their own
supply, and having two supplies fight over VDD is a good way to damage one
of them -- the tool refuses outright when it sees external power. A board
with no other supply needs it, so it is an argument rather than a decision
made here.
"""

from __future__ import annotations

import pathlib
import re
import tempfile
import shutil
import subprocess

from ..progress import Progress, banner, complete, error, info, note, stage

#: Where MPLAB X puts ipecmd, relative to a version directory.
_IPE_LEAF = pathlib.Path("mplab_platform") / "mplab_ipe"
_INSTALL_ROOTS = (
    r"H:\MPLABX",
    r"C:\Program Files\Microchip\MPLABX",
    r"C:\Program Files (x86)\Microchip\MPLABX",
    "/opt/microchip/mplabx",
)

# Public compatibility marker for callers that require serial-bound tool
# selection.  Increment this when the selector/readback contract changes.
PICKIT3_BACKEND_API = 1


#: dsPIC30F and dsPIC33 are the only parts here whose MPLAB name does not
#: begin with PIC. Reading the prefix off the part number rather than off
#: the catalog's family keeps a PIC24F right: it shares the family and does
#: not share the prefix.
_DSPIC_PREFIXES = ("30F", "33F", "33E", "33C")


def mplab_device_name(part: str) -> str:
    """The name MPLAB's device database uses for *part*.

    The catalog stores what is printed on the package -- ``16F877A``,
    ``30F4013`` -- and ipecmd accepts exactly that, so every request built
    below passes it through unchanged.

    MPLAB's other command-line tools want the full name, ``PIC16F877A``,
    and are not as forgiving as ipecmd: a device they do not recognise is
    skipped rather than refused, so a short name there produces a tool that
    appears to hang rather than one that objects. Anything driving a part
    through something other than ipecmd should ask for the name here.
    """
    name = part.upper()
    prefix = "dsPIC" if name.startswith(_DSPIC_PREFIXES) else "PIC"
    return prefix + name

#: ipecmd is chatty and most of it is banner. These are the lines that say
#: something happened, and the ones that say something went wrong.
_PROGRESS = re.compile(
    r"(Target device .* found|Target voltage detected|Device Revision|"
    r"Programming|Verif|Erasing|Program Memory|Configuration Memory|"
    r"EEData|Program complete|Read complete|Operation Succeeded)", re.I)
#: The one line that proves the programmer reached the target rather than
#: merely opening. `-P<part> -TPPK3` on its own never contacts the part --
#: it validates arguments and succeeds against a wrong part number too.
_FOUND = re.compile(r"Target device .* found", re.I)
#: What ipecmd prints when it finished the job. The verdict has to rest on
#: this rather than on whether any error-shaped line appeared: a PICkit 3
#: that was last asked to power the target keeps that setting, so the next
#: run reports the refusal, recovers, programs and verifies cleanly -- and
#: reading the refusal as failure turns a good upload into a red error.
_SUCCESS = re.compile(r"(Operation Succeeded|Verify Succeeded)", re.I)
#: What ipecmd prints when the session never reached the tool's scripting
#: engine. It still exits 0 and can print "Operation Succeeded" for a
#: request that was never executed -- seen on this bench from a tool whose
#: application firmware had stopped reading its USB pipe -- so this line
#: vetoes a verdict that the success line alone would carry.
_CONNECT_FAIL = re.compile(r"Connection Failed", re.I)
_TROUBLE = re.compile(
    r"(fail|error|unable|no device|cannot|invalid|mismatch|"
    r"target device was not found|check your connections|"
    r"target device .* not found|Operation Aborted)", re.I)


def supports_pk3(ipecmd: pathlib.Path) -> bool:
    """Whether this MPLAB X install can drive a PICkit 3 at all.

    Support was removed after the 5.x line. A 6.x ipecmd asked for -TPPK3
    answers "Could not find device", which sends people to the Pack Manager
    to fix a device that is not the problem -- so the version is checked
    here and the real reason is reported instead.
    """
    for part in ipecmd.resolve().parts:
        if part.lower().startswith("v") and part[1:2].isdigit():
            try:
                major = int(part[1:].split(".")[0])
            except ValueError:
                continue
            return major < 6
    # An install whose version cannot be read from the path is given the
    # benefit of the doubt: ipecmd's own error is better than a guess.
    return True


def find_ipecmd(require_pk3: bool = True) -> pathlib.Path | None:
    """Locate ipecmd: recorded path, PATH, then the usual MPLAB X installs.

    With *require_pk3* an install that cannot drive a PICkit 3 is skipped,
    so a 6.x sitting beside a 5.x does not shadow the one that works.
    """
    from .. import config

    found: list[pathlib.Path] = []
    recorded = config.tool_path("pickit3")
    if recorded is not None:
        found.append(recorded)
    which = shutil.which("ipecmd")
    if which:
        found.append(pathlib.Path(which))
    for root in (pathlib.Path(r) for r in _INSTALL_ROOTS):
        if not root.is_dir():
            continue
        for version in sorted(root.iterdir(), reverse=True):
            for name in ("ipecmd.exe", "ipecmd"):
                candidate = version / _IPE_LEAF / name
                if candidate.is_file():
                    found.append(candidate)
    if not found:
        return None
    if require_pk3:
        for candidate in found:
            if supports_pk3(candidate):
                return candidate
        # Something is installed, but none of it drives a PICkit 3. Saying
        # so is the caller's job; returning one anyway would produce
        # ipecmd's misleading "Could not find device".
        return None
    return found[0]


def _missing() -> int:
    """No usable ipecmd. Say which of the two problems it is."""
    unusable = find_ipecmd(require_pk3=False)
    if unusable is not None:
        error(
            f"the MPLAB X at {unusable.parents[2].name} cannot drive a "
            "PICkit 3: support for it was removed after the 5.x line",
            title="this MPLAB X is too new for a PICkit 3",
            hints=("install MPLAB X 5.35, the last release that drives one, "
                   "and record it with "
                   "`python -m niusburner setup --pickit3 <path to ipecmd>`",
                   "or fit a PICkit 4 or 5, which current MPLAB X supports",
                   "asked for -TPPK3, a 6.x ipecmd answers 'Could not find "
                   "device', which is not the real problem"))
        return 1
    error(
        "ipecmd was not found, and a PICkit 3 speaks only Microchip's own "
        "protocol",
        title="no PIC programmer",
        hints=("install MPLAB X 5.35, which ships ipecmd and drives a "
               "PICkit 3, then re-run `python -m niusburner setup`",
               "already installed elsewhere? "
               "`python -m niusburner setup --pickit3 <path to ipecmd>`"))
    return 1


def _report(output: str) -> None:
    """Pass through the lines that say what happened, drop the banner."""
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if _PROGRESS.search(line):
            info(line)
        else:
            note(line)


def _trouble(output: str) -> tuple[str, ...]:
    """The lines that look like the reason, most useful first."""
    hits = [line.strip() for line in output.splitlines()
            if line.strip() and _TROUBLE.search(line)]
    # Keep the order but drop repeats: ipecmd says the same thing twice.
    seen: set[str] = set()
    unique = []
    for line in hits:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return tuple(unique[:6])


def _bundled_jre(ipecmd: pathlib.Path) -> pathlib.Path | None:
    """The JRE MPLAB X ships with itself, if this install has one.

    ipecmd.exe is a launcher that finds a JRE through the registry, and on
    a machine whose only Java is a modern JDK it simply reports "Unable to
    locate JRE" and stops. The jar beside it runs fine on the 1.8 the
    installer put in sys/java, so that is what is used when it is there.
    """
    try:
        root = ipecmd.resolve().parents[2]      # <install>/mplab_platform/..
    except IndexError:
        return None
    java = root / "sys" / "java"
    if not java.is_dir():
        return None
    for child in sorted(java.iterdir(), reverse=True):
        for name in ("java.exe", "java"):
            candidate = child / "bin" / name
            if candidate.is_file():
                return candidate
    return None


def invocation(ipecmd: pathlib.Path) -> tuple[list[str], pathlib.Path]:
    """How to run this ipecmd, and from where.

    The jar has to run with the mplab_ipe directory as its working
    directory or it cannot find its own configuration, and the locale is
    pinned because the output is parsed: a localised install otherwise
    reports success and failure in a language these patterns do not match.
    """
    home = ipecmd.resolve().parent
    jar = home / "ipecmd.jar"
    java = _bundled_jre(ipecmd)
    if java is not None and jar.is_file():
        return ([str(java), "-Duser.language=en", "-Duser.country=US",
                 "-jar", str(jar)], home)
    return ([str(ipecmd)], home)


def tool_selector(tool_serial: str | None = None) -> str:
    """Return an exact IPECMD selector, or the legacy type selector.

    IPECMD documents ``-TS<serial>`` for selecting one programming tool when
    several tools are connected.  Keep the type-only selector for existing
    interactive callers, while safety-oriented callers can require the exact
    serial form.
    """
    if tool_serial is None:
        return "-TPPK3"
    serial = str(tool_serial).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", serial):
        raise ValueError("PICkit tool serial must be one exact token")
    return f"-TS{serial}"


def _run(tool: pathlib.Path, args: list[str],
         cwd: pathlib.Path) -> tuple[int, str]:
    prefix, home = invocation(tool)
    try:
        done = subprocess.run(prefix + args, cwd=str(home),
                              capture_output=True, timeout=300)
    except FileNotFoundError:
        return 1, f"could not run {tool}"
    except subprocess.TimeoutExpired:
        return 1, "ipecmd did not finish within 300 s"
    # Whatever the console codepage is, never crash on it.
    raw = (done.stdout or b"") + (done.stderr or b"")
    return done.returncode, raw.decode("utf-8", "replace")


_HINTS = (
    "check the ICSP header: MCLR, VDD, VSS, PGD and PGC, pin 1 to pin 1",
    "the part must be powered -- pass --power to let the programmer supply "
    "it, or power the board itself",
    "a PICkit 3 must be in its MPLAB firmware, not the standalone "
    "programmer-app firmware",
)

#: Some failures have one obvious cause, and a generic hint list buries it.
#: Ordered by where the failure sits in the chain, not by topic: the first
#: match leads the report, and a run can print several of these at once. A
#: tool that never connected also prints that it could not power or read the
#: target, and sending the reader to the board's supply for that wastes the
#: one thing they have -- so the failures nearest the host come first, and
#: only then the ones that need the target to have been reached at all.
_SPECIFIC_HINTS = (
    # A tool whose application firmware has stopped reading its USB pipe
    # enumerates cleanly and times out on the first scripting packet. No
    # ICSP hint fixes that: the tool needs a power cycle, and if the state
    # survives one, the button held while plugging in makes the next
    # connect reload its firmware.
    ("connection failed",
     "the PICkit 3 itself did not answer, before any ICSP traffic: unplug "
     "and replug its USB, then retry -- and if it still fails, hold the "
     "tool's button while plugging in so its firmware is reloaded"),
    ("cannot supply power to the target",
     "this board has its own supply: select the plain PICkit 3 programmer, "
     "not the one that powers the target"),
    ("Invalid Device ID",
     "the part answering is not the one selected -- check the board choice "
     "and pin 1 of the ICSP header"),
    # Both of these were reported as "the part must be powered -- pass
    # --power", which is right for one of them and actively misleading for
    # the other: --power was already given, and giving it harder does not
    # help a tool that cannot source the current.
    ("could not detect target voltage",
     "nothing is powering the board: give it its own supply, or pass "
     "--power to let the programmer do it"),
    ("but the target VDD is measured to be",
     "the programmer is supplying VDD and the board is pulling it down -- "
     "a PICkit 3 sources only tens of milliamps, so this board needs its "
     "own supply and --power should be left off"),
)


def _hints_for(output: str) -> tuple[str, ...]:
    """Lead with the hint that matches what actually went wrong."""
    lead = tuple(hint for needle, hint in _SPECIFIC_HINTS
                 if needle.lower() in output.lower())
    return lead + _HINTS


def probe(target: str, power: bool = False, *, tool_serial: str | None = None,
          scratch_root: pathlib.Path | None = None, run: bool = True) -> int:
    """Read the device ID. Programs nothing.

    Reading is meant to be observation, so the part is released when the
    read finishes. Without ``-OL`` the programmer keeps MCLR asserted after
    it exits, and the part stays in reset until something else releases it
    -- so checking on a running board silently stops it, and every check
    after the first one then agrees that it is not running. Pass
    ``run=False`` when the caller genuinely wants it held.
    """
    tool = find_ipecmd()
    if tool is None:
        return _missing()
    banner(f"PIC Flash Console - Target: {target}")
    stage(0, "Connecting", "PICkit 3 over ICSP")
    # Reading the configuration word is the cheapest operation that makes
    # the tool talk to the silicon: a bare connect reports success even
    # with nothing on the header, and even against the wrong part number.
    # The read goes to a scratch file nobody looks at; the device ID line
    # it prints on the way is the answer.
    if scratch_root is not None:
        scratch_root = pathlib.Path(scratch_root)
        scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as scratch:
        args = [f"-P{target}", tool_selector(tool_serial),
                "-GCF" + str(pathlib.Path(scratch) / "id.hex")]
        if run:
            args.append("-OL")
        if power:
            args.append("-W")
        code, output = _run(tool, args, pathlib.Path(scratch))
    if code != 0 or not _FOUND.search(output):
        error("the programmer did not identify the part",
              title="no answer over ICSP",
              hints=_hints_for(output), details=_trouble(output))
        return 1
    _report(output)
    stage(100, "Connected", target)
    return 0


def flash(image: pathlib.Path, target: str, power: bool = False,
          run: bool = True, *, tool_serial: str | None = None) -> int:
    """Erase, program and verify *image* on *target* through a PICkit 3."""
    tool = find_ipecmd()
    if tool is None:
        return _missing()
    if not image.is_file():
        error(f"image not found: {image}", title="nothing to program",
              hints=("did Verify succeed?",))
        return 1

    banner(f"PIC Flash Console - Target: {target}")
    stage(0, "Connecting", "PICkit 3 over ICSP")

    args = [f"-P{target}", tool_selector(tool_serial), f"-F{image}",
            "-E", "-M", "-Y"]
    if power:
        args.append("-W")
    if run:
        args.append("-OL")
    note(" ".join([tool.name, *args]))

    # ipecmd does not report progress as it goes, so there is nothing
    # honest to animate: one line before, one after, and its own output in
    # between rather than a bar that would be pretending.
    stage(20, "Programming", image.name)
    code, output = _run(tool, args, image.parent)
    problems = _trouble(output)
    if (code != 0 or not _SUCCESS.search(output)
            or _CONNECT_FAIL.search(output)):
        error("ipecmd did not report a clean program and verify",
              title="programming failed", hints=_hints_for(output),
              details=problems)
        _report(output)
        return 1
    _report(output)
    if not run:
        complete("Programmed, held in reset",
                 "Reset             : held - waiting for the caller to "
                 "release it")
        return 0
    complete("Upload complete",
             "Reset             : released - board running the new firmware",
             "Power             : "
             + ("supplied by the programmer" if power
                else "supplied by the board, not the programmer"))
    return 0


def reset(target: str, power: bool = False, *,
          tool_serial: str | None = None) -> int:
    """Release the part from reset without touching its flash."""
    tool = find_ipecmd()
    if tool is None:
        return _missing()
    args = [f"-P{target}", tool_selector(tool_serial), "-OL"]
    if power:
        args.append("-W")
    code, output = _run(tool, args, pathlib.Path.cwd())
    if code != 0 or _CONNECT_FAIL.search(output):
        error("could not release the part", title="reset failed",
              hints=_hints_for(output), details=_trouble(output))
        return 1
    info(f"reset  {target} released from reset")
    return 0


def readback(output: pathlib.Path, target: str, power: bool = False, *,
             tool_serial: str | None = None, run: bool = True) -> int:
    """Read the entire target into *output* using one selected programmer.

    Reading is meant to be observation, so the part is released when the
    read finishes. Without ``-OL`` the programmer keeps MCLR asserted after
    it exits, and the part stays in reset until something else releases it
    -- so checking on a running board silently stops it, and every check
    after the first one then agrees that it is not running. Pass
    ``run=False`` when the caller genuinely wants it held.
    """
    tool = find_ipecmd()
    if tool is None:
        return _missing()
    output = pathlib.Path(output)
    if not output.parent.is_dir():
        error(f"output directory not found: {output.parent}",
              title="cannot save PIC readback")
        return 1
    args = [f"-P{target}", tool_selector(tool_serial), f"-GF{output}"]
    if run:
        args.append("-OL")
    if power:
        args.append("-W")
    code, result = _run(tool, args, output.parent)
    if (code != 0 or not output.is_file()
            or _CONNECT_FAIL.search(result)):
        error("the PIC readback did not produce an image",
              title="readback failed", hints=_hints_for(result),
              details=_trouble(result))
        _report(result)
        return 1
    _report(result)
    return 0
