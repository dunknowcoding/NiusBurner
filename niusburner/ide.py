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
from .progress import error, info, note, stage

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
    # Regenerate from the catalog so a newly added part appears in the menu.
    (dest / "boards.txt").write_text(
        render_boards_txt(), encoding="utf-8", newline="\n")
    tools = dest / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    # The IDE runs nb_host from the sketchbook, so record both halves of what
    # it needs there: which interpreter, and where the package lives when it
    # is not pip-installed on that interpreter.
    (tools / "python.path").write_text(
        str(Path(sys.executable).resolve()), encoding="utf-8", newline="\n")
    (tools / "niusburner.path").write_text(
        str(HERE.parent.resolve()), encoding="utf-8", newline="\n")
    return dest


#: Menus every board offers, and the value each choice passes to the host.
#: The first entry of each is the default the IDE selects.
MENUS = (
    ("optimize", "Optimize", (
        ("size", "Size (default)", "size"),
        ("speed", "Speed", "speed"),
        ("none", "None", "none"),
    )),
    ("debug", "Debug info", (
        ("none", "None (default)", "none"),
        ("symbols", "Symbols and listings", "symbols"),
    )),
    ("compiler", "Compiler", (
        ("auto", "Auto-detect SDCC (default)", "auto"),
        ("configured", "Use the path from `niusburner setup --sdcc`",
         "configured"),
    )),
)


def render_boards_txt() -> str:
    """Build boards.txt from the board catalog.

    Generated rather than hand-written, because the two drifted: a part
    added to the catalog was compilable from the command line and simply
    absent from the IDE menu, with nothing to say so.
    """
    from . import boards as boards_mod

    out = [
        "# NiusBurner 8051 boards (SDCC).",
        "#",
        "# Copyright 2026 dunknowcoding (NiusRobotLab)",
        "# SPDX-License-Identifier: Apache-2.0",
        "#",
        "# Generated from niusburner/boards.json by "
        "`python -m niusburner setup`.",
        "# Edit the catalog, not this file.",
        "#",
        "# Defaults are the safe answer, not the fastest one: Size, because",
        "# these parts run out of flash long before cycles; no debug info,",
        "# because symbols cost build time and disk rather than flash; and",
        "# auto-detection, because SDCC is normally where its installer put",
        "# it.",
        "",
    ]
    out += ["menu.%s=%s" % (key, label) for key, label, _ in MENUS]
    out.append("")

    for board in boards_mod.all_boards().values():
        flash_kb = board.code_size // 1024
        how = ("USB-ISP" if board.programmer == "usbisp_hid"
               else "serial bootloader" if board.programmer == "stcgal"
               else "compile only")
        out += [
            "# %s" % ("-" * 70),
            "# %s" % board.note,
            "%s.name=%s (%d KB, %s)" % (
                board.id, board.part.upper(), flash_kb, how),
            "%s.upload.tool=niusburner" % board.id,
            "%s.upload.protocol=%s" % (board.id, board.programmer),
            "%s.upload.maximum_size=%d" % (board.id, board.code_size),
            "%s.upload.maximum_data_size=%d" % (board.id, board.iram_size),
            # A serial-bootloader part is programmed through the port the
            # IDE already asks for, so that one needs it.
            "%s.upload.require_upload_port=%s" % (
                board.id, "true" if board.programmer == "stcgal" else "false"),
            "%s.build.mcu=%s" % (board.id, board.part),
            "%s.build.f_cpu=%dL" % (board.id, board.f_cpu),
            "%s.build.board=%s" % (board.id, board.part.upper()),
            "%s.build.core=niusburner" % board.id,
            "%s.build.variant=standard" % board.id,
            "%s.build.nb_board=%s" % (board.id, board.id),
            "%s.build.extra_flags=" % board.id,
            "",
        ]
        for key, _, choices in MENUS:
            for name, label, value in choices:
                out.append("%s.menu.%s.%s=%s" % (board.id, key, name, label))
                out.append("%s.menu.%s.%s.build.nb_%s=%s" % (
                    board.id, key, name, key, value))
            out.append("")
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.rstrip() + "\n"


def _touch(path: Path, data: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


#: Board-menu values arrive as strings and may be empty when the IDE has no
#: value for them. Empty always means the documented default.
def _menu(value: str | None, allowed: tuple[str, ...], default: str) -> str:
    text = (value or "").strip().lower()
    return text if text in allowed else default


def resolve_compiler(choice: str) -> Path | None:
    """SDCC for this build: the configured path, or auto-detection.

    "auto" is the default and looks on PATH first, then the usual install
    directories. "configured" uses the path recorded by
    `niusburner setup --sdcc <path>`, and says so if there is not one.
    """
    from . import config

    if _menu(choice, ("auto", "configured"), "auto") == "configured":
        recorded = config.sdcc_path()
        if recorded is None:
            raise ValueError(
                "the board menu asks for the configured compiler, but none is "
                "recorded. Run `python -m niusburner setup --sdcc "
                "<path to sdcc>` or switch Tools > Compiler back to "
                "Auto-detect.")
        return recorded
    return None


def cmd_compile(sketch: Path, build_path: Path, board: str,
                optimize: str = "size", debug: str = "none",
                compiler_choice: str = "auto") -> int:
    out = build_path / "niusburner"
    optimize = _menu(optimize, ("size", "speed", "none"), "size")
    debug_symbols = _menu(debug, ("none", "symbols"), "none") == "symbols"
    # No banner here: the upload tool prints it once, and Verify runs in a
    # separate process that would otherwise repeat the whole thing.
    stage(0, "Compiling", f"target {board}")
    try:
        compiler = resolve_compiler(compiler_choice)
        plan = workflow.plan_compile(sketch, board, output=out)
        result = workflow.compile_plan(
            plan, out, compiler=compiler,
            optimize=optimize, debug_symbols=debug_symbols)
    except (OSError, ValueError, KeyError) as exc:
        error(str(exc), title="compile failed")
        return 1
    shutil.copy2(result.image, build_path / "firmware.ihx")
    spec = plan.board
    note(f"{len(plan.sources)} translation unit(s), optimize={optimize}"
         + (", debug symbols" if debug_symbols else ""))
    stage(100, "Compiled",
          f"flash {result.program_bytes}/{spec.code_size} B "
          f"({100 * result.program_bytes / spec.code_size:.1f}%)  "
          f"iram {result.iram_bytes}/{spec.iram_size} B")
    print(f"Sketch uses {result.program_bytes} bytes of program storage space.")
    return 0


def cmd_flash(image: Path, board: str, programmer: str = "",
              port: str = "") -> int:
    # The IDE Upload button is the erase acknowledgement. Flash the HEX
    # produced during Verify; upload.pattern does not receive the sketch path.
    from . import boards as boards_mod
    try:
        spec = boards_mod.get_board(board)
    except KeyError as exc:
        error(str(exc), title="unknown board")
        return 1
    wanted = (programmer or spec.programmer).strip() or spec.programmer
    if wanted != spec.programmer:
        error(
            f"Tools > Programmer is set to {wanted}, but {spec.id} is "
            f"programmed with {spec.programmer}",
            title="programmer does not match the board",
            hints=(f"select Tools > Programmer > {spec.programmer}",
                   "or select a board that uses the programmer you have"))
        return 1
    if not spec.flashable:
        error(
            f"{spec.id} is programmed with {spec.programmer} "
            f"({spec.status}), which the Upload button does not drive yet",
            title="this board compiles but cannot be flashed here",
            hints=("the sketch itself compiled cleanly",
                   "see docs/families/8051.md for the route this part needs"))
        return 1
    if not image.is_file():
        error(f"image not found: {image}",
              title="nothing to upload", hints=("did Verify succeed?",))
        return 1
    try:
        # `burn` enters ISP and checks the signature itself, so a separate
        # probe here would only be a second round trip.
        return flash.burn(
            target=spec.part, image=image, confirm=spec.part,
            programmer=spec.programmer, port=port,
            state_policy="replace",
        )
    except (OSError, ValueError) as exc:
        error(str(exc), title="upload failed")
        return 1


def cmd_hex(build_path: Path, project_name: str) -> int:
    src = build_path / "firmware.ihx"
    dest = build_path / f"{project_name}.hex"
    if not src.is_file():
        error(f"no firmware.ihx in {build_path}",
              title="nothing to package", hints=("did Verify succeed?",))
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
        error("no recipe named",
              title="Arduino host called with no arguments",
              hints=("commands: compile, preproc, dummy-o, dummy-ar, hex, "
                     "size, flash",))
        return 2
    cmd = argv[0]
    rest = argv[1:]
    try:
        if cmd == "compile":
            return cmd_compile(
                Path(rest[0]), Path(rest[1]), rest[2],
                optimize=rest[3] if len(rest) > 3 else "size",
                debug=rest[4] if len(rest) > 4 else "none",
                compiler_choice=rest[5] if len(rest) > 5 else "auto")
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
            return cmd_flash(
                Path(rest[0]), rest[1],
                programmer=rest[2] if len(rest) > 2 else "",
                port=rest[3] if len(rest) > 3 else "")
    except (IndexError, ValueError) as exc:
        error(str(exc), title="bad Arduino recipe arguments",
              hints=("re-run `python -m niusburner setup` to refresh the "
                     "board package",))
        return 2
    error(f"unknown Arduino host command {cmd!r}", title="bad recipe")
    return 2
