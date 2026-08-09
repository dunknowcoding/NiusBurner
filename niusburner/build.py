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
) -> Mcs51Build:
    """Compile C through optimized assembly and fail closed on exact limits."""

    if not sources or code_size <= 0 or iram_size <= 0:
        raise ValueError("sources and positive memory capacities are required")
    resolved_sources = [path.resolve(strict=True) for path in sources]
    resolved_includes = [path.resolve(strict=True) for path in includes]
    compiler_path = compiler or pathlib.Path(shutil.which("sdcc") or "")
    if not compiler_path or not compiler_path.is_file():
        raise FileNotFoundError("SDCC is not available; install it or pass --compiler")
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
        str(compiler_path), "-mmcs51", "--model-small", "--std-c99",
        "--opt-code-size", "--iram-size", str(iram_size),
        "--code-size", str(code_size),
    ]
    for include in resolved_includes:
        flags.extend(("-I", str(include)))

    objects: list[str] = []
    assemblies: list[pathlib.Path] = []
    for index, source in enumerate(resolved_sources):
        stem = f"unit_{index:02d}_{source.stem}"
        obj = f"{stem}.rel"
        _run([*flags, "-c", str(source), "-o", obj], output)
        assembly = output / f"{stem}.asm"
        if not assembly.is_file():
            raise ValueError(f"SDCC did not retain optimized assembly for {source.name}")
        objects.append(obj)
        assemblies.append(assembly)

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

    # Keep the optimized assembly and exact accounting artifacts. Relocatable
    # objects and assembler listings are reproducible scratch, not deliverables.
    for name in objects:
        (output / name).unlink(missing_ok=True)
    for pattern in ("*.lst", "*.rst", "*.sym", "*.lk"):
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
        },
        "limits": {
            "linked_system_program_bytes": program_limit,
            "kernel_data_bytes": data_limit,
        },
        "measured": {
            "linked_system_program_bytes": program_bytes,
            "kernel_data_bytes": kernel_data,
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
        image, map_file, memory_file, manifest, program_bytes, kernel_data)
