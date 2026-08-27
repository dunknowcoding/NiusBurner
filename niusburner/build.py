"""Reproducible, bounded source builds for legacy MCU toolchains.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

This module owns compilation and exact linker accounting. It deliberately does
not execute firmware: building, packaging, programming, and execution are four
separate states and callers may choose any execution environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Mcs51Build:
    image: pathlib.Path
    map_file: pathlib.Path
    memory_file: pathlib.Path
    manifest: pathlib.Path
    program_bytes: int
    kernel_data_bytes: int | None
    iram_bytes: int = 0
    stack_bytes: int = 0
    xram_bytes: int = 0
    optimize: str = "size"
    symbols: tuple[pathlib.Path, ...] = ()


def _run(command: list[str], cwd: pathlib.Path) -> str:
    completed = subprocess.run(
        command, cwd=cwd, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"tool exited {completed.returncode}: {pathlib.Path(command[0]).name}\n"
            f"{completed.stdout or ''}")
    return completed.stdout or ""


#: How the SDCC front end is asked to spend its effort. "size" is the default
#: because these parts run out of flash long before they run out of cycles;
#: "none" exists so a build can keep statement order recognisable.
OPTIMIZE_FLAGS = {
    "size": ("--opt-code-size", "--fomit-frame-pointer",
             "--max-allocs-per-node", "25000"),
    "speed": ("--opt-code-speed", "--fomit-frame-pointer",
              "--max-allocs-per-node", "25000"),
    "none": (),
}


def parse_sdcc_iram(memory_report: str) -> tuple[int, int]:
    """(bytes of internal RAM allocated, bytes left for the stack).

    SDCC prints the stack base, and everything below it is allocated data,
    register banks and bit space. That is the number worth watching on a part
    with 256 bytes of internal RAM in total.
    """
    match = re.search(
        r"Stack starts at:\s*0x([0-9A-Fa-f]+).*?with\s+(\d+)\s+bytes available",
        memory_report,
        re.S,
    )
    if not match:
        return 0, 0
    return int(match.group(1), 16), int(match.group(2))


def parse_sdcc_xram_bytes(memory_report: str) -> int:
    match = re.search(
        r"EXTERNAL RAM\s+(?:0x[0-9A-Fa-f]+\s+0x[0-9A-Fa-f]+\s+)?(\d+)",
        memory_report)
    return int(match.group(1)) if match else 0


def parse_sdcc_program_bytes(memory_report: str) -> int:
    match = re.search(
        r"ROM/EPROM/FLASH\s+0x[0-9A-Fa-f]+\s+0x[0-9A-Fa-f]+\s+(\d+)",
        memory_report,
    )
    if not match:
        raise ValueError("SDCC memory report lacks an exact program-byte total")
    return int(match.group(1))


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_sdcc() -> pathlib.Path | None:
    """Locate SDCC: the recorded path, then PATH, then the usual installs.

    The recorded path wins because it is the only one a person chose on
    purpose; everything after it is a guess, in decreasing order of how good
    a guess it is.
    """
    from . import config

    recorded = config.sdcc_path()
    if recorded is not None:
        return recorded
    which = shutil.which("sdcc")
    if which:
        return pathlib.Path(which)
    for candidate in (
        pathlib.Path(r"C:\Program Files\SDCC\bin\sdcc.exe"),
        pathlib.Path(r"C:\Program Files (x86)\SDCC\bin\sdcc.exe"),
        pathlib.Path("/usr/bin/sdcc"),
        pathlib.Path("/usr/local/bin/sdcc"),
    ):
        if candidate.is_file():
            return candidate
    home = os.environ.get("SDCC_HOME") or os.environ.get("SDCC")
    if home:
        for name in ("sdcc.exe", "sdcc"):
            candidate = pathlib.Path(home) / "bin" / name
            if candidate.is_file():
                return candidate
    root = config.toolchain_root()
    if root is not None:
        for name in ("sdcc.exe", "sdcc"):
            for candidate in sorted(root.glob(f"*/bin/{name}")) +                     sorted(root.glob(f"sdcc*/{name}")):
                if candidate.is_file():
                    return candidate
    return None


_ASM_SUFFIXES = {".s", ".asm"}
_PREPROCESS = re.compile(
    r"(?m)^\s*#\s*(include|define|if|ifdef|ifndef|endif|undef|pragma)\b"
)


def find_sdas8051(compiler: pathlib.Path | None = None) -> pathlib.Path | None:
    """Locate SDCC's MCS-51 assembler next to sdcc, then on PATH."""
    sdcc = compiler or find_sdcc()
    names = ("sdas8051.exe", "sdas8051")
    if sdcc is not None:
        for name in names:
            candidate = sdcc.parent / name
            if candidate.is_file():
                return candidate
    which = shutil.which("sdas8051")
    return pathlib.Path(which) if which else None


def find_sdcpp(compiler: pathlib.Path | None = None) -> pathlib.Path | None:
    sdcc = compiler or find_sdcc()
    names = ("sdcpp.exe", "sdcpp")
    if sdcc is not None:
        for name in names:
            candidate = sdcc.parent / name
            if candidate.is_file():
                return candidate
    which = shutil.which("sdcpp")
    return pathlib.Path(which) if which else None


def _is_asm_source(path: pathlib.Path) -> bool:
    return path.suffix.lower() in _ASM_SUFFIXES


def _assemble_mcs51(
    source: pathlib.Path,
    obj: str,
    output: pathlib.Path,
    *,
    compiler: pathlib.Path,
    includes: list[pathlib.Path],
    defines: list[str],
) -> pathlib.Path:
    assembler = find_sdas8051(compiler)
    if assembler is None or not assembler.is_file():
        raise FileNotFoundError(
            "sdas8051 is not next to SDCC. Re-install SDCC from "
            "https://sourceforge.net/projects/sdcc/files/"
        )
    src = source
    text = source.read_text(encoding="utf-8", errors="replace")
    if _PREPROCESS.search(text):
        cpp = find_sdcpp(compiler)
        if cpp is None or not cpp.is_file():
            raise FileNotFoundError(
                f"{source.name} uses the C preprocessor; sdcpp was not found next to SDCC"
            )
        pp = output / (pathlib.Path(obj).stem + ".pp.asm")
        cmd = [str(cpp), "-P", "-o", str(pp)]
        for name in defines:
            cmd.append(f"-D{name}")
        for include in includes:
            cmd.extend(("-I", str(include)))
        cmd.append(str(source))
        _run(cmd, output)
        src = pp
    # sdas8051 -plosgffw <rel> <asm>  (output is the first file, no -o).
    _run([str(assembler), "-plosgffw", obj, str(src)], output)
    return src


def _load_contract(path: pathlib.Path | None) -> tuple[int | None, int | None]:
    if path is None:
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    kernel_data = data.get("kernel_data_bytes")
    ladder = data.get("resource_ladder")
    if (not isinstance(kernel_data, int) or kernel_data < 0 or
            not isinstance(ladder, dict)):
        raise ValueError("contract receipt lacks bounded data/program limits")
    final_limit = ladder.get("maximum_linked_image_bytes")
    if final_limit is None:
        # v0.2.0 receipts used this name for the final link ceiling.
        final_limit = ladder.get("maximum_linked_system_bytes")
    if not isinstance(final_limit, int) or final_limit <= 0:
        raise ValueError("contract receipt lacks bounded data/program limits")
    return kernel_data, final_limit


def build_mcs51(
    sources: list[pathlib.Path],
    includes: list[pathlib.Path],
    output: pathlib.Path,
    *,
    compiler: pathlib.Path | None = None,
    contract: pathlib.Path | None = None,
    code_size: int = 2048,
    iram_size: int = 128,
    program_limit: int | None = None,
    data_limit: int | None = None,
    require_version: str | None = None,
    model: str = "small",
    stack_auto: bool = False,
    xram_size: int = 0,
    defines: list[str] | None = None,
    optimize: str = "size",
    debug_symbols: bool = False,
) -> Mcs51Build:
    """Compile C through optimized assembly and fail closed on exact limits.

    *optimize* picks what SDCC spends its effort on; see OPTIMIZE_FLAGS.
    *debug_symbols* asks SDCC for a symbol database and keeps the listings
    and symbol tables that are otherwise scratch, so a linked image can be
    read back against the source it came from.
    """

    if not sources or code_size <= 0 or iram_size <= 0:
        raise ValueError("sources and positive memory capacities are required")
    if model not in {"small", "medium", "large"}:
        raise ValueError("SDCC model must be small, medium or large")
    if optimize not in OPTIMIZE_FLAGS:
        raise ValueError(
            f"unknown optimize mode {optimize!r}; "
            f"choose from {', '.join(sorted(OPTIMIZE_FLAGS))}")
    resolved_sources = [path.resolve(strict=True) for path in sources]
    resolved_includes = [path.resolve(strict=True) for path in includes]
    compiler_path = compiler or find_sdcc()
    if compiler_path is None or not compiler_path.is_file():
        raise FileNotFoundError(
            "SDCC is not available. Install it from https://sourceforge.net/projects/sdcc/files/ "
            "and re-run `python -m niusburner setup`, or pass --compiler"
        )
    compiler_path = compiler_path.resolve(strict=True)
    version = _run([str(compiler_path), "--version"], pathlib.Path.cwd()).strip()
    if "SDCC" not in version:
        raise ValueError("selected compiler did not identify itself as SDCC")
    if require_version and require_version not in version:
        raise ValueError(f"SDCC version does not contain required text {require_version!r}")

    kernel_data, receipt_program_limit = _load_contract(contract)
    if program_limit is None:
        program_limit = receipt_program_limit
    elif receipt_program_limit is not None and program_limit > receipt_program_limit:
        raise ValueError("explicit program limit exceeds the contract image capacity")
    if data_limit is not None and kernel_data is None:
        raise ValueError("--data-limit requires a contract receipt with kernel data")

    output.mkdir(parents=True, exist_ok=True)
    flags = [
        str(compiler_path), "-mmcs51", f"--model-{model}", "--std-c99",
        *OPTIMIZE_FLAGS[optimize],
        "--iram-size", str(iram_size),
        "--code-size", str(code_size),
        "--xram-size", str(xram_size),
    ]
    if debug_symbols:
        flags.append("--debug")
    if stack_auto:
        flags.append("--stack-auto")
    for name in defines or []:
        flags.append(f"-D{name}")
    for include in resolved_includes:
        flags.extend(("-I", str(include)))

    objects: list[str] = []
    assemblies: list[pathlib.Path] = []
    for index, source in enumerate(resolved_sources):
        stem = f"unit_{index:02d}_{source.stem}"
        obj = f"{stem}.rel"
        if _is_asm_source(source):
            kept = _assemble_mcs51(
                source, obj, output,
                compiler=compiler_path,
                includes=resolved_includes,
                defines=defines or [],
            )
            assemblies.append(kept)
        else:
            _run([*flags, "-c", str(source), "-o", obj], output)
            assembly = output / f"{stem}.asm"
            if not assembly.is_file():
                raise ValueError(
                    f"SDCC did not retain optimized assembly for {source.name}")
            assemblies.append(assembly)
        objects.append(obj)

    _run([*flags, *objects, "-o", "firmware.ihx"], output)
    image = output / "firmware.ihx"
    map_file = output / "firmware.map"
    memory_file = output / "firmware.mem"
    for artifact in (image, map_file, memory_file):
        if not artifact.is_file():
            raise ValueError(f"SDCC did not emit {artifact.name}")
    program_bytes = parse_sdcc_program_bytes(
        memory_file.read_text(encoding="utf-8", errors="replace"))
    if program_bytes > code_size:
        raise ValueError("linked image exceeds the selected device program capacity")
    if program_limit is not None and program_bytes > program_limit:
        raise ValueError("linked image violates the selected program limit")
    if data_limit is not None and kernel_data is not None and kernel_data > data_limit:
        raise ValueError("kernel-owned data violates the contract limit")

    report = memory_file.read_text(encoding="utf-8", errors="replace")
    iram_bytes, stack_bytes = parse_sdcc_iram(report)
    xram_bytes = parse_sdcc_xram_bytes(report)

    # Keep the optimized assembly and exact accounting artifacts. Relocatable
    # objects and assembler listings are reproducible scratch, not
    # deliverables -- unless symbols were asked for, where they are the point.
    symbols: list[pathlib.Path] = []
    for name in objects:
        (output / name).unlink(missing_ok=True)
    keep = ("*.cdb", "*.sym", "*.lst", "*.rst") if debug_symbols else ()
    for pattern in ("*.lst", "*.rst", "*.sym", "*.lk", "*.cdb"):
        if pattern in keep:
            symbols.extend(sorted(output.glob(pattern)))
            continue
        for path in output.glob(pattern):
            path.unlink()

    manifest_data = {
        "schema": "niusburner-mcs51-build-v1",
        "compiler": {
            "name": "sdcc",
            "version": version.splitlines()[0] if version else "",
        },
        "target": {
            "family": "mcs51",
            "program_capacity_bytes": code_size,
            "iram_capacity_bytes": iram_size,
            "xram_capacity_bytes": xram_size,
            "model": model,
        },
        "limits": {
            "linked_system_program_bytes": program_limit,
            "kernel_data_bytes": data_limit,
        },
        "measured": {
            "linked_system_program_bytes": program_bytes,
            "kernel_data_bytes": kernel_data,
            "iram_bytes": iram_bytes,
            "stack_bytes_free": stack_bytes,
            "xram_bytes": xram_bytes,
        },
        "build": {
            "optimize": optimize,
            "debug_symbols": bool(debug_symbols),
        },
        "sources": [
            {"name": source.name, "sha256": _sha256(source)}
            for source in resolved_sources
        ],
        "artifacts": {
            "image": {"name": image.name, "sha256": _sha256(image)},
            "map": {"name": map_file.name, "sha256": _sha256(map_file)},
            "memory": {"name": memory_file.name, "sha256": _sha256(memory_file)},
            "assembly": [
                {"name": path.name, "sha256": _sha256(path)}
                for path in assemblies
            ],
        },
    }
    manifest = output / "build-manifest.json"
    manifest.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return Mcs51Build(
        image, map_file, memory_file, manifest, program_bytes, kernel_data,
        iram_bytes=iram_bytes, stack_bytes=stack_bytes, xram_bytes=xram_bytes,
        optimize=optimize, symbols=tuple(symbols))
