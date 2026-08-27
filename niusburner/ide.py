"""Install a sketchbook board package so Arduino IDE Verify/Upload drive NiusBurner.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

The Arduino builder has no GCC requirement: every recipe is a command
template. This module copies a tiny platform into the sketchbook
`hardware/` folder. Verify runs SDCC through NiusBurner (C, BASIC C++,
sdas8051 `.S` / `__asm`); Upload flashes the USB-ISP. The IDE does not
compile AVR GNU assembly or C++ for the 8051.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import display as display_mod
from . import flash, workflow

HERE = Path(__file__).parent
PLATFORM_SRC = HERE / "arduino" / "mcs51"
VENDOR = "niusrobotlab"
ARCHITECTURE = "mcs51"


def preferred_sketchbook() -> Path | None:
    """First Arduino sketchbook that already exists, or the Documents default."""
    existing = [book for book in display_mod.arduino_sketchbooks() if book.is_dir()]
    if existing:
        return existing[0]
    books = display_mod.arduino_sketchbooks()
    return books[0] if books else None


def platform_dest(sketchbook: Path) -> Path:
    return sketchbook / "hardware" / VENDOR / ARCHITECTURE


def install_arduino_platform(sketchbook: Path | None = None) -> Path:
    """Copy the board package into a sketchbook and record this Python."""
    book = sketchbook or preferred_sketchbook()
    if book is None:
        raise FileNotFoundError(
            "no Arduino sketchbook found. Set ARDUINO_SKETCHBOOK or "
            "create Documents/Arduino, then re-run setup."
        )
    if not PLATFORM_SRC.is_dir():
        raise FileNotFoundError(f"board package missing at {PLATFORM_SRC}")
    dest = platform_dest(book)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PLATFORM_SRC, dest, dirs_exist_ok=True)
    (dest / "tools" / "python.path").write_text(
        str(Path(sys.executable).resolve()), encoding="utf-8", newline="\n")
    return dest


def _touch(path: Path, data: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def cmd_compile(sketch: Path, build_path: Path, board: str) -> int:
    out = build_path / "niusburner"
    try:
        plan = workflow.plan_compile(sketch, board, output=out)
        result = workflow.compile_plan(plan, out)
    except (OSError, ValueError, KeyError) as exc:
        print(f"niusburner: {exc}", file=sys.stderr)
        return 1
    shutil.copy2(result.image, build_path / "firmware.ihx")
    print(f"Sketch uses {result.program_bytes} bytes of program storage space.")
    return 0


def cmd_flash(image: Path, board: str) -> int:
    # The IDE Upload button is the erase acknowledgement. Flash the HEX
    # produced during Verify; upload.pattern does not receive the sketch path.
    from . import boards as boards_mod
    try:
        spec = boards_mod.get_board(board)
    except KeyError as exc:
        print(f"niusburner: {exc}", file=sys.stderr)
        return 1
    if not spec.flashable:
        print(
            f"niusburner: compile succeeded, but this IDE board cannot flash "
            f"{spec.id} yet (programmer {spec.programmer}).",
            file=sys.stderr,
        )
        return 1
    if not image.is_file():
        print(f"niusburner: image not found: {image}", file=sys.stderr)
        return 1
    try:
        rc = flash.probe(target=spec.part, confirm=spec.part)
        if rc != 0:
            return rc
        return flash.burn(
            target=spec.part, image=image, confirm=spec.part,
            state_policy="replace",
        )
    except (OSError, ValueError) as exc:
        print(f"niusburner: {exc}", file=sys.stderr)
        return 1


def cmd_hex(build_path: Path, project_name: str) -> int:
    src = build_path / "firmware.ihx"
    dest = build_path / f"{project_name}.hex"
    if not src.is_file():
        print(f"niusburner: no firmware.ihx in {build_path} (Verify failed?)",
              file=sys.stderr)
        return 1
    shutil.copy2(src, dest)
    return 0


def cmd_size(build_path: Path) -> int:
    mem = build_path / "niusburner" / "firmware.mem"
    if not mem.is_file():
        print("Sketch uses 0 bytes of program storage space.")
        return 0
    from . import build as build_mod
    try:
        n = build_mod.parse_sdcc_program_bytes(
            mem.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        n = 0
    print(f"Sketch uses {n} bytes of program storage space.")
    return 0


def cmd_preproc(source: Path, dest: Path) -> int:
    text = source.read_text(encoding="utf-8", errors="replace") if source.is_file() else ""
    if str(dest) in {"NUL", "nul", "/dev/null"}:
        return 0
    _touch(dest, text.encode("utf-8"))
    return 0


def arduino_main(argv: list[str]) -> int:
    if not argv:
        print("niusburner Arduino host: compile|preproc|dummy-o|dummy-ar|hex|size|flash",
              file=sys.stderr)
        return 2
    cmd = argv[0]
    rest = argv[1:]
    try:
        if cmd == "compile":
            return cmd_compile(Path(rest[0]), Path(rest[1]), rest[2])
        if cmd == "preproc":
            return cmd_preproc(Path(rest[0]), Path(rest[1]))
        if cmd == "dummy-o":
            _touch(Path(rest[0]))
            return 0
        if cmd == "dummy-ar":
            _touch(Path(rest[0]))
            return 0
        if cmd == "hex":
            return cmd_hex(Path(rest[0]), rest[1])
        if cmd == "size":
            return cmd_size(Path(rest[0]))
        if cmd == "flash":
            return cmd_flash(Path(rest[0]), rest[1])
    except (IndexError, ValueError) as exc:
        print(f"niusburner: bad Arduino recipe arguments: {exc}", file=sys.stderr)
        return 2
    print(f"niusburner: unknown Arduino host command {cmd!r}", file=sys.stderr)
    return 2
