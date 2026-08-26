"""Plan, compile, and upload a sketch onto a named board.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

This is the user-facing workflow. Layers below it stay separate on purpose:

    sketch / display / boards   what to build
    build                       how to invoke SDCC
    flash / backends            how to program silicon

`build-mcs51` remains the low-level compiler driver. This module chooses the
board, wraps an .ino, finds NiusDisplay when the sketch needs it, and refuses
combinations that cannot work (C++ on SDCC, graphics on a part with no XRAM).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import boards as boards_mod
from . import build, display as display_mod, flash, sketch as sketch_mod
from .boards import Board
from .build import Mcs51Build
from .display import DisplayLib
from .sketch import RUNTIME_MCS51, Sketch

RUNTIME_HEADER = "nius_sketch.h"
RUNTIME_C = RUNTIME_MCS51 / "nius_sketch.c"


@dataclass(frozen=True)
class CompilePlan:
    board: Board
    sketch: Sketch
    sources: tuple[Path, ...]
    includes: tuple[Path, ...]
    defines: tuple[str, ...]
    model: str
    stack_auto: bool
    xram_size: int
    runtime: str                       # "niusdisplay" | "sketch" | "freestanding"
    library: Path | None
    generated: Path | None


def default_output(sketch: Sketch, board: Board) -> Path:
    return sketch.directory / ".niusburner" / board.id


def plan_compile(
    sketch_path: Path,
    board_name: str,
    *,
    library: Path | None = None,
    xram_size: int | None = None,
    defines: list[str] | None = None,
    output: Path | None = None,
) -> CompilePlan:
    board = boards_mod.get_board(board_name)
    if board.family != "mcs51" or board.compiler != "sdcc":
        raise ValueError(
            f"board {board.id} is {board.compiler}/{board.family}; "
            "only SDCC mcs51 boards can be compiled by this command today"
        )
    sk = sketch_mod.resolve_sketch(sketch_path)
    out = (output or default_output(sk, board)).resolve()

    cxx = sketch_mod.cxx_reason(sk.text)
    if cxx:
        raise sketch_mod.cxx_error(sk, cxx)

    extra_defines = tuple(defines or ())
    ram = board.xram_size if xram_size is None else xram_size

    if sketch_mod.uses_niusdisplay(sk):
        lib_root = display_mod.find_niusdisplay(library, sketch_dir=sk.directory)
        if lib_root is None:
            raise display_mod.missing_library_error()
        lib = display_mod.collect_for_sketch(lib_root, sk)
        return _plan_with_display(board, sk, out, lib, ram, extra_defines)

    return _plan_without_display(board, sk, out, ram, extra_defines)


def _plan_with_display(
    board: Board,
    sk: Sketch,
    output: Path,
    lib: DisplayLib,
    xram_size: int,
    extra_defines: tuple[str, ...],
) -> CompilePlan:
    if lib.needs_xram and xram_size <= 0:
        names = ", ".join(display_mod.graphics_stems(lib.sources))
        raise ValueError(
            f"this sketch pulls in NiusDisplay graphics ({names}), which SDCC "
            "places in XRAM (--model-large). "
            f"{board.id} on a minimum board has no external RAM.\n"
            "  - Use the TM1637 / segment / HD44780 C API (those fit in IRAM), or\n"
            "  - Fit SRAM and pass --xram-size <bytes> (then --model-large is used)."
        )
    model = "large" if xram_size > 0 else board.model
    generated = None
    sketch_unit = sk.path
    if sk.kind == "ino":
        generated = output / "sketch.c"
        sketch_mod.wrap_ino(sk, generated, runtime_header="NiusDuino.h")
        sketch_unit = generated
    sources = (sketch_unit, *sk.extra_c, *lib.sources)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in sources:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    defines = tuple(dict.fromkeys((*lib.defines, *extra_defines)))
    return CompilePlan(
        board=board,
        sketch=sk,
        sources=tuple(unique),
        includes=lib.includes,
        defines=defines,
        model=model,
        stack_auto=True,
        xram_size=xram_size,
        runtime="niusdisplay",
        library=lib.root,
        generated=generated,
    )


def _plan_without_display(
    board: Board,
    sk: Sketch,
    output: Path,
    xram_size: int,
    extra_defines: tuple[str, ...],
) -> CompilePlan:
    generated = None
    sources: list[Path]
    includes: list[Path] = []
    defines = extra_defines
    runtime = "freestanding"

    if sk.has_main:
        sources = [sk.path, *sk.extra_c]
    elif sk.kind == "ino" or sk.has_setup_loop:
        if sk.kind == "ino" and not sk.has_setup_loop:
            raise ValueError(
                f"{sk.path.name} has no setup()/loop(). On 8051 a .ino is C that "
                "reads like a sketch; add those two functions, or write a .c "
                "with main()."
            )
        if sk.kind == "ino":
            generated = output / "sketch.c"
            sketch_mod.wrap_ino(sk, generated, runtime_header=RUNTIME_HEADER)
            sources = [generated, *sk.extra_c, RUNTIME_C]
        else:
            sources = [sk.path, *sk.extra_c, RUNTIME_C]
        defines = ("ND_NIUS_SKETCH_MAIN", *extra_defines)
        runtime = "sketch"
        includes = [RUNTIME_MCS51]
    else:
        raise ValueError(
            f"{sk.path.name} has neither main() nor setup()/loop()"
        )

    return CompilePlan(
        board=board,
        sketch=sk,
        sources=tuple(sources),
        includes=tuple(includes),
        defines=defines,
        model=board.model,
        stack_auto=False,
        xram_size=xram_size,
        runtime=runtime,
        library=None,
        generated=generated,
    )


def compile_plan(
    plan: CompilePlan,
    output: Path,
    *,
    compiler: Path | None = None,
) -> Mcs51Build:
    output.mkdir(parents=True, exist_ok=True)
    if plan.generated is not None:
        header = "NiusDuino.h" if plan.runtime == "niusdisplay" else RUNTIME_HEADER
        sketch_mod.wrap_ino(plan.sketch, plan.generated, runtime_header=header)
    return build.build_mcs51(
        list(plan.sources),
        list(plan.includes),
        output,
        compiler=compiler,
        code_size=plan.board.code_size,
        iram_size=plan.board.iram_size,
        model=plan.model,
        stack_auto=plan.stack_auto,
        xram_size=plan.xram_size,
        defines=list(plan.defines),
    )


def upload_image(plan: CompilePlan, image: Path, *, skip_probe: bool = False) -> int:
    board = plan.board
    if not board.flashable:
        raise ValueError(
            f"compile succeeded, but `upload` cannot flash {board.id} yet "
            f"(programmer {board.programmer}, status {board.status}). "
            "See docs/families/8051.md."
        )
    if not skip_probe:
        rc = flash.probe(target=board.part, confirm=board.part)
        if rc != 0:
            return rc
    return flash.burn(
        target=board.part,
        image=image,
        confirm=board.part,
        state_policy="replace",
    )
