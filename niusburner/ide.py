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
PLATFORM_ROOT = HERE / "arduino"
PLATFORM_SRC = PLATFORM_ROOT / "mcs51"

#: One Arduino board package per architecture. The IDE keys its
#: whole toolchain off the architecture directory name, so these
#: cannot be merged into one package however similar they look.
ARCHITECTURES = ("mcs51", "pic16")
VENDOR = "niusrobotlab"
ARCHITECTURE = "mcs51"


def preferred_sketchbook() -> Path | None:
    """First Arduino sketchbook that already exists, or the Documents default."""
    existing = [book for book in display_mod.arduino_sketchbooks() if book.is_dir()]
    if existing:
        return existing[0]
    books = display_mod.arduino_sketchbooks()
    return books[0] if books else None


def platform_dest(sketchbook: Path, architecture: str = ARCHITECTURE) -> Path:
    return sketchbook / "hardware" / VENDOR / architecture


def install_arduino_platform(sketchbook: Path | None = None) -> Path:
    """Copy every board package into a sketchbook and record this Python.

    Returns the sketchbook's vendor directory, which is the one thing a
    person needs to see to know where the packages went.
    """
    book = sketchbook or preferred_sketchbook()
    if book is None:
        raise FileNotFoundError(
            "no Arduino sketchbook found. Set ARDUINO_SKETCHBOOK or "
            "create Documents/Arduino, then re-run setup."
        )
    last: Path | None = None
    for architecture in ARCHITECTURES:
        source = PLATFORM_ROOT / architecture
        if not source.is_dir():
            raise FileNotFoundError(f"board package missing at {source}")
        dest = platform_dest(book, architecture)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest, dirs_exist_ok=True)
        # Regenerate from the catalog so a newly added part appears in the
        # menu of whichever architecture it belongs to.
        (dest / "boards.txt").write_text(
            render_boards_txt(architecture), encoding="utf-8", newline="\n")
        tools = dest / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        # The IDE runs nb_host from the sketchbook, so record both halves of
        # what it needs there: which interpreter, and where the package lives
        # when it is not pip-installed on that interpreter.
        (tools / "python.path").write_text(
            str(Path(sys.executable).resolve()), encoding="utf-8",
            newline="\n")
        (tools / "niusburner.path").write_text(
            str(HERE.parent.resolve()), encoding="utf-8", newline="\n")
        last = dest
    return last.parent if last is not None else book


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
    ("reset", "Power switch", (
        ("none", "None - interrupt power by hand (default)", "none"),
        ("dtr", "Adapter DTR switches VDD", "dtr"),
        ("rts", "Adapter RTS switches VDD", "rts"),
    )),
    ("entry", "Bootloader entry", (
        ("none", "Interrupt power by hand (default)", "none"),
        ("soft", "Sketch reboots itself into the bootloader", "soft"),
    )),
    ("compiler", "Compiler", (
        ("auto", "Auto-detect SDCC (default)", "auto"),
        ("configured", "Use the path from `niusburner setup --sdcc`",
         "configured"),
    )),
)


def render_boards_txt(family: str = "mcs51") -> str:
    """Build boards.txt from the board catalog.

    Generated rather than hand-written, because the two drifted: a part
    added to the catalog was compilable from the command line and simply
    absent from the IDE menu, with nothing to say so.
    """
    from . import boards as boards_mod

    out = [
        "# NiusBurner %s boards." % family,
        "#",
        "# Copyright 2026 dunknowcoding (NiusRobotLab)",
        "# SPDX-License-Identifier: Apache-2.0",
        "#",
        "# Generated from niusburner/boards.json by "
        "`python -m niusburner setup`.",
        "# Edit the catalog, not this file.",
        "#",
        "# Defaults are the safe answer, not the fastest one: Size, because",
        "# these parts run out of room long before cycles; no debug info,",
        "# because symbols cost build time and disk rather than flash; and",
        "# auto-detection, because a compiler is normally where its own",
        "# installer put it.",
        "",
    ]
    # A menu declared with no board offering choices renders as an empty
    # Tools entry, so the bootloader-entry menu is declared only where at
    # least one board can actually use it.
    soft_entry = any(b.programmer == "stcgal"
                     for b in boards_mod.all_boards().values()
                     if b.family == family)
    out += ["menu.%s=%s" % (key, label) for key, label, _ in MENUS
            if key != "entry" or soft_entry]
    out.append("")

    for board in boards_mod.all_boards().values():
        if board.family != family:
            continue
        # A PIC16 instruction is one 14-bit word, so its size is quoted in
        # words. Calling that a kilobyte would be wrong by more than two.
        if board.family == "pic16":
            size = "%d K words" % (board.code_size // 1024)
        else:
            size = "%d KB" % (board.code_size // 1024)
        how = {"usbisp_hid": "USB-ISP",
               "stcgal": "serial bootloader",
               "pickit3": "PICkit 3"}.get(board.programmer, "compile only")
        out += [
            "# %s" % ("-" * 70),
            "# %s" % board.note,
            "%s.name=%s (%s, %s)" % (
                board.id, board.part.upper(), size, how),
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
            # Only a part programmed through its own bootloader can be asked
            # to reboot into it. On an ISP part the choice would be inert,
            # and an inert menu entry is worse than an absent one.
            if key == "entry" and board.programmer != "stcgal":
                continue
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


#: Which recordable tool compiles for which family.
COMPILER_FOR = {"mcs51": "sdcc", "pic16": "xc8"}


def resolve_compiler(choice: str, family: str = "mcs51") -> Path | None:
    """The compiler for this build: the configured path, or auto-detection.

    "auto" is the default and lets the family's own finder look on PATH and
    in the usual install directories. "configured" uses the path recorded by
    `niusburner setup --<tool>`, and says so if there is not one.
    """
    from . import config

    if _menu(choice, ("auto", "configured"), "auto") != "configured":
        return None
    tool = COMPILER_FOR.get(family, "sdcc")
    recorded = config.tool_path(tool)
    if recorded is None:
        raise ValueError(
            f"the board menu asks for the configured compiler, but no {tool} "
            f"is recorded. Run `python -m niusburner setup --{tool} "
            f"<path to {tool}>` or switch Tools > Compiler back to "
            "Auto-detect.")
    return recorded


def cmd_compile(sketch: Path, build_path: Path, board: str,
                optimize: str = "size", debug: str = "none",
                compiler_choice: str = "auto", entry: str = "none") -> int:
    from . import boards as boards_mod

    out = build_path / "niusburner"
    optimize = _menu(optimize, ("size", "speed", "none"), "size")
    debug_symbols = _menu(debug, ("none", "symbols"), "none") == "symbols"
    isp_entry = _menu(entry, ("none", "soft"), "none") == "soft"
    # No banner here: the upload tool prints it once, and Verify runs in a
    # separate process that would otherwise repeat the whole thing.
    stage(0, "Compiling", f"target {board}")
    try:
        spec_family = boards_mod.get_board(board).family
        compiler = resolve_compiler(compiler_choice, spec_family)
        plan = workflow.plan_compile(sketch, board, output=out)
        result = workflow.compile_plan(
            plan, out, compiler=compiler,
            optimize=optimize, debug_symbols=debug_symbols,
            isp_entry=isp_entry)
    except (OSError, ValueError, KeyError) as exc:
        error(str(exc), title="compile failed")
        return 1
    # Keep the compiler's own extension: .ihx from SDCC, .hex from XC8.
    shutil.copy2(result.image, build_path / ("firmware" + result.image.suffix))
    spec = plan.board
    note(f"{len(plan.sources)} translation unit(s), optimize={optimize}"
         + (", debug symbols" if debug_symbols else "")
         + (", bootloader entry" if isp_entry else ""))
    if spec.family == "pic16":
        detail = (f"flash {result.program_words}/{spec.code_size} words "
                  f"({100 * result.program_words / spec.code_size:.1f}%)  "
                  f"ram {result.data_bytes}/{spec.iram_size} B")
    else:
        detail = (f"flash {result.program_bytes}/{spec.code_size} B "
                  f"({100 * result.program_bytes / spec.code_size:.1f}%)  "
                  f"iram {result.iram_bytes}/{spec.iram_size} B")
    stage(100, "Compiled", detail)
    print(f"Sketch uses {result.program_bytes} bytes of program storage space.")
    return 0


def cmd_flash(image: Path, board: str, programmer: str = "",
              port: str = "", reset_pin: str = "") -> int:
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
            reset_pin=_menu(reset_pin, ("dtr", "rts"), ""),
            state_policy="replace",
        )
    except (OSError, ValueError) as exc:
        error(str(exc), title="upload failed")
        return 1


def cmd_hex(build_path: Path, project_name: str) -> int:
    # Whichever the compiler produced. Both are Intel HEX; the extension is
    # only a house style, and the IDE always wants .hex on the end.
    src = next((build_path / name for name in ("firmware.hex", "firmware.ihx")
                if (build_path / name).is_file()),
               build_path / "firmware.ihx")
    dest = build_path / f"{project_name}.hex"
    if not src.is_file():
        error(f"no firmware.ihx in {build_path}",
              title="nothing to package", hints=("did Verify succeed?",))
        return 1
    shutil.copy2(src, dest)
    return 0


def cmd_size(build_path: Path) -> int:
    """What the IDE puts in its size bar.

    Read from the build manifest, which every family writes, rather than
    from one compiler's memory report. The unit differs -- words on a PIC16,
    bytes on an 8051 -- and the IDE has only one number to show, so it gets
    the one that matches `upload.maximum_size` for that board.
    """
    import json

    manifest = build_path / "niusburner" / "build-manifest.json"
    used = 0
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            measured = data.get("measured", {})
            used = int(measured.get("program_words")
                       or measured.get("linked_system_program_bytes") or 0)
        except (ValueError, TypeError):
            used = 0
    if not used:
        # SDCC's own report, for a build that predates the manifest.
        mem = build_path / "niusburner" / "firmware.mem"
        if mem.is_file():
            from . import build as build_mod
            try:
                used = build_mod.parse_sdcc_program_bytes(
                    mem.read_text(encoding="utf-8", errors="replace"))
            except ValueError:
                used = 0
    print(f"Sketch uses {used} bytes of program storage space.")
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
                compiler_choice=rest[5] if len(rest) > 5 else "auto",
                entry=rest[6] if len(rest) > 6 else "none")
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
                port=rest[3] if len(rest) > 3 else "",
                reset_pin=rest[4] if len(rest) > 4 else "")
    except (IndexError, ValueError) as exc:
        error(str(exc), title="bad Arduino recipe arguments",
              hints=("re-run `python -m niusburner setup` to refresh the "
                     "board package",))
        return 2
    error(f"unknown Arduino host command {cmd!r}", title="bad recipe")
    return 2
