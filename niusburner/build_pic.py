"""Build a PIC16 image with Microchip XC8.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

XC8 is one driver that compiles and links in a single call, so this is
shorter than the SDCC path: no separate assembler step, no per-unit .rel to
collect. What it does need is a part name (`-mcpu=16F877A`) and a clock, and
it reports what the image cost in its own format, which is parsed here so
the usage meter reads the same for every family.

Assembly is not touched, exactly as on the other families: a `.S` or `.as`
file beside the sketch is handed to the same driver, which passes it to
pic-as, and an `asm("...")` statement inside C reaches the compiler as
written.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass

#: Where the Windows installer and the toolchain-root layout put XC8.
_INSTALL_ROOTS = (
    r"C:\Program Files\Microchip\xc8",
    r"C:\Program Files (x86)\Microchip\xc8",
    "/opt/microchip/xc8",
    "/usr/local/xc8",
)

_ASM_SUFFIXES = {".s", ".as", ".asm"}


@dataclass(frozen=True)
class Pic16Build:
    """What a PIC16 build produced and what it cost."""

    image: pathlib.Path
    manifest: pathlib.Path
    program_words: int
    program_size: int
    data_bytes: int
    data_size: int
    eeprom_bytes: int
    sources: tuple[pathlib.Path, ...]
    symbols: tuple[pathlib.Path, ...]
    optimize: str
    version: str

    @property
    def program_bytes(self) -> int:
        """Words, reported as bytes so one usage meter serves every family.

        A PIC16 instruction is 14 bits in a 14-bit-wide word, so the honest
        unit here is words; `program_words` is the real number and this is
        the one the shared reporting understands.
        """
        return self.program_words


def _run(command: list[str], cwd: pathlib.Path) -> str:
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True,
                              text=True, timeout=600)
    except FileNotFoundError as exc:
        raise ValueError(f"tool not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"tool timed out: {command[0]}") from exc
    if done.returncode != 0:
        raise ValueError(
            f"tool exited {done.returncode}: {pathlib.Path(command[0]).name}\n"
            + (done.stdout or "") + (done.stderr or ""))
    return (done.stdout or "") + (done.stderr or "")


def find_xc8() -> pathlib.Path | None:
    """Locate the XC8 driver: recorded path, PATH, then the usual installs."""
    from . import config

    recorded = config.tool_path("xc8")
    if recorded is not None:
        return recorded
    which = shutil.which("xc8-cc")
    if which:
        return pathlib.Path(which)
    roots = [pathlib.Path(r) for r in _INSTALL_ROOTS]
    toolchains = config.toolchain_root()
    if toolchains is not None:
        roots.insert(0, toolchains / "pic" / "xc8")
    for root in roots:
        if not root.is_dir():
            continue
        # Newest version directory first, so a machine with several installed
        # gets the one most likely to know the part.
        for version in sorted(root.iterdir(), reverse=True):
            for name in ("xc8-cc.exe", "xc8-cc"):
                candidate = version / "bin" / name
                if candidate.is_file():
                    return candidate
    return None


#: XC8 prints a memory summary per space; these are the lines worth keeping.
_USED = re.compile(
    r"^\s*(Program space|Data space|EEPROM space)\s+used\s+"
    r"[0-9A-Fa-f]+h\s+\(\s*(\d+)\)\s+of\s+[0-9A-Fa-f]+h\s+(?:words|bytes)",
    re.M)


def parse_xc8_usage(report: str) -> dict[str, int]:
    """{'program': words, 'data': bytes, 'eeprom': bytes} from XC8's summary."""
    key = {"Program space": "program", "Data space": "data",
           "EEPROM space": "eeprom"}
    out: dict[str, int] = {}
    for space, used in _USED.findall(report):
        out[key[space]] = int(used)
    return out


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_pic(
    sources: list[pathlib.Path],
    includes: list[pathlib.Path],
    output: pathlib.Path,
    *,
    compiler: pathlib.Path | None = None,
    part: str = "16F877A",
    family: str = "pic16",
    f_cpu: int = 20000000,
    program_size: int = 8192,
    data_size: int = 368,
    defines: list[str] | None = None,
    optimize: str = "size",
) -> Pic16Build:
    """Compile and link *sources* into a HEX image for *part*."""
    driver = compiler or find_xc8()
    if driver is None or not driver.is_file():
        raise FileNotFoundError(
            "XC8 was not found. Install MPLAB XC8 and re-run "
            "`python -m niusburner setup`.\n"
            "  Already installed somewhere else? Record it once:\n"
            "    python -m niusburner setup --xc8 \"<path to xc8-cc>\"\n"
            "  Searched: the recorded path, PATH, the usual install "
            "directories, then EMBD_TOOLCHAINS/pic/xc8.")
    driver = driver.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    # XC8 runs with the output directory as its working directory, so every
    # path handed to it has to be absolute or it resolves against itself.
    output = output.resolve()
    version = _run([str(driver), "--version"], pathlib.Path.cwd()).strip()

    image = output / "firmware.hex"
    command = [
        str(driver),
        f"-mcpu={part}",
        # XC8 wants the part without a leading PIC and is case-insensitive.
        f"-D_XTAL_FREQ={f_cpu}UL",
        f"-DNIUS_FOSC={f_cpu}UL",
        "-o", str(image),
    ]
    command += {"size": ["-O2"], "speed": ["-O2"], "none": ["-O0"]}[optimize]
    for path in includes:
        command += ["-I", str(pathlib.Path(path).resolve(strict=True))]
    for macro in defines or []:
        command += [f"-D{macro}"]
    resolved: list[pathlib.Path] = []
    for path in sources:
        resolved.append(pathlib.Path(path).resolve(strict=True))
    command += [str(p) for p in resolved]

    report = _run(command, output)
    usage = parse_xc8_usage(report)
    if not image.is_file():
        raise ValueError("XC8 reported success but produced no HEX image")

    # The HEX image and its manifest are the deliverables; everything
    # else XC8 leaves behind is scratch.
    symbols: list[pathlib.Path] = []

    manifest = output / "build-manifest.json"
    import json

    manifest.write_text(json.dumps({
        "family": family,
        "part": part,
        "compiler": driver.name,
        "version": version.splitlines()[0] if version else "",
        "build": {"optimize": optimize, "f_cpu": f_cpu},
        "measured": {
            "program_words": usage.get("program", 0),
            "data_bytes": usage.get("data", 0),
            "eeprom_bytes": usage.get("eeprom", 0),
        },
        "limits": {"program_words": program_size, "data_bytes": data_size},
        "artifacts": {"image": image.name, "sha256": _sha256(image)},
    }, indent=2) + "\n", encoding="utf-8", newline="\n")

    return Pic16Build(
        image=image,
        manifest=manifest,
        program_words=usage.get("program", 0),
        program_size=program_size,
        data_bytes=usage.get("data", 0),
        data_size=data_size,
        eeprom_bytes=usage.get("eeprom", 0),
        sources=tuple(resolved),
        symbols=tuple(symbols),
        optimize=optimize,
        version=version.splitlines()[0] if version else "",
    )


#: The former name, kept so an out-of-tree caller keeps working.
build_pic16 = build_pic
