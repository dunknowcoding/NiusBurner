"""XC16 driver: compile and link a sketch for a 16-bit PIC.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

XC16 differs from XC8 in three ways that matter here.

It links against a per-part linker script rather than finding one from the
part name, so the script is named explicitly. It produces an ELF, and the
HEX a programmer wants comes from a second pass through xc16-bin2hex. And
it has no size utility at all -- the memory figures come from the linker's
own report, which has to be asked for with --report-mem.

Program memory is counted in bytes on this family, not in the words a
mid-range PIC16 uses.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil

from .build_pic import Pic16Build, _run

#: Where a manual XC16 install usually lands.
_INSTALL_ROOTS = (
    r"C:\embd_toolchains\pic\xc16",
    r"C:\Program Files\Microchip\xc16",
    r"C:\Program Files (x86)\Microchip\xc16",
    "/opt/microchip/xc16",
)

#: The linker prints one of these per memory region.
_TOTAL = re.compile(
    r'Total\s+"(?P<region>program|data)"\s+memory used \(bytes\):'
    r'\s+0x[0-9a-fA-F]+\s+\((?P<count>\d+)\)')


def find_xc16() -> pathlib.Path | None:
    """Locate xc16-gcc: recorded path, PATH, then the usual installs."""
    from . import config

    recorded = config.tool_path("xc16")
    if recorded and pathlib.Path(recorded).is_file():
        return pathlib.Path(recorded)

    found = shutil.which("xc16-gcc") or shutil.which("xc16-gcc.exe")
    if found:
        return pathlib.Path(found)

    import os

    roots = list(_INSTALL_ROOTS)
    env = os.environ.get("EMBD_TOOLCHAINS")
    if env:
        roots.insert(0, str(pathlib.Path(env) / "pic" / "xc16"))
    for root in roots:
        base = pathlib.Path(root)
        if not base.is_dir():
            continue
        matches = sorted(base.glob("*/bin/xc16-gcc.exe")) + \
            sorted(base.glob("*/bin/xc16-gcc"))
        if matches:
            return matches[-1]
    return None


def parse_xc16_usage(report: str) -> dict[str, int]:
    """{'program': bytes, 'data': bytes} from the linker's --report-mem."""
    out: dict[str, int] = {}
    for match in _TOTAL.finditer(report):
        out[match.group("region")] = int(match.group("count"))
    return out


def build_pic24(
    sources: list[pathlib.Path],
    includes: list[pathlib.Path],
    output: pathlib.Path,
    *,
    compiler: pathlib.Path | None = None,
    part: str = "30F4013",
    family: str = "pic24",
    f_cpu: int = 7372800,
    program_size: int = 49152,
    data_size: int = 2048,
    defines: list[str] | None = None,
    optimize: str = "size",
) -> Pic16Build:
    """Compile and link *sources* into a HEX image for *part*."""
    driver = compiler or find_xc16()
    if driver is None or not driver.is_file():
        raise FileNotFoundError(
            "XC16 was not found. Install MPLAB XC16 and re-run "
            "`python -m niusburner setup`.\n"
            "  Already installed somewhere else? Record it once:\n"
            "    python -m niusburner setup --xc16 \"<path to xc16-gcc>\"\n"
            "  Searched: the recorded path, PATH, the usual install "
            "directories, then EMBD_TOOLCHAINS/pic/xc16.")
    driver = driver.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    output = output.resolve()

    version = _run([str(driver), "--version"], pathlib.Path.cwd()).strip()
    elf = output / "firmware.elf"
    image = output / "firmware.hex"

    command = [
        str(driver),
        f"-mcpu={part}",
        f"-D_XTAL_FREQ={f_cpu}UL",
        f"-DNIUS_FOSC={f_cpu}UL",
        "-o", str(elf),
    ]
    command += {"size": ["-Os"], "speed": ["-O2"], "none": ["-O0"]}[optimize]
    for path in includes:
        command += ["-I", str(pathlib.Path(path).resolve(strict=True))]
    for macro in defines or []:
        command += [f"-D{macro}"]
    command += [str(pathlib.Path(p).resolve(strict=True)) for p in sources]
    # The script is named rather than inferred, and the report is the only
    # source of size figures this toolchain offers.
    command.append(f"-Wl,--script=p{part}.gld,--report-mem")

    report = _run(command, output)
    if not elf.is_file():
        raise ValueError("XC16 reported success but produced no ELF")

    bin2hex = driver.with_name(driver.name.replace("gcc", "bin2hex"))
    if not bin2hex.is_file():
        raise FileNotFoundError(f"xc16-bin2hex not found beside {driver}")
    _run([str(bin2hex), str(elf)], output)
    if not image.is_file():
        raise ValueError("xc16-bin2hex produced no HEX image")

    usage = parse_xc16_usage(report)
    program = usage.get("program", 0)
    data = usage.get("data", 0)
    if program > program_size:
        raise ValueError(
            f"program memory: {program} bytes used of {program_size}")
    if data > data_size:
        raise ValueError(f"data memory: {data} bytes used of {data_size}")

    resolved = [pathlib.Path(p).resolve() for p in sources]
    manifest = output / "build-manifest.json"
    manifest.write_text(json.dumps({
        "family": family,
        "part": part,
        "compiler": driver.name,
        "version": version.splitlines()[0] if version else "",
        "build": {"optimize": optimize},
        "measured": {"program_bytes": program, "data_bytes": data},
        "limits": {"program_size": program_size, "data_size": data_size},
        "sources": [p.name for p in resolved],
    }, indent=2) + "\n", encoding="utf-8")

    return Pic16Build(
        image=image,
        manifest=manifest,
        program_words=program,          # bytes on this family; see program_unit
        program_size=program_size,
        data_bytes=data,
        data_size=data_size,
        eeprom_bytes=0,
        sources=tuple(resolved),
        symbols=(),
        optimize=optimize,
        version=version.splitlines()[0] if version else "",
    )
