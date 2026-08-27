"""Plan, compile, and upload a sketch onto a named board.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

This is the user-facing workflow. Layers below it stay separate on purpose:

    sketch / display / boards   what to build
    build                       how to invoke SDCC
    flash / backends            how to program silicon

`build-mcs51` remains the low-level compiler driver. This module chooses the
board, wraps an .ino, finds NiusDisplay when the sketch needs it, lowers
BASIC Arduino C++ to C via mounted adapters, assembles sibling `.S` files,
and refuses combinations that cannot work (real C++ on SDCC, graphics on a
part with no XRAM).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import boards as boards_mod
from . import build, cxxlower, display as display_mod, flash, sketch as sketch_mod
from .boards import Board
from .build import Mcs51Build
from .display import DisplayLib
from .sketch import RUNTIME_MCS51, Sketch

RUNTIME_HEADER = "nius_sketch.h"
RUNTIME_C = RUNTIME_MCS51 / "nius_sketch.c"
SERIAL_C = RUNTIME_MCS51 / "nius_serial.c"


def _with_sketch_dir(sk: Sketch, includes: list[Path]) -> list[Path]:
    """Put the sketch directory on the include path.

    An .ino is wrapped into <output>/.niusburner/<board>/sketch.c, so a
    quoted #include in the sketch resolves against the generated file, not
    against the folder the header actually sits in. Arduino puts the sketch
    folder on the include path; so does this.
    """
    root = sk.directory.resolve()
    if root not in {path.resolve() for path in includes}:
        includes.append(sk.directory)
    return includes


def _link_serial(
    sk: Sketch,
    sources: tuple[Path, ...],
    includes: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    if "nius_serial_" not in sk.text:
        return sources, includes
    src = list(sources)
    inc = list(includes)
    if SERIAL_C.resolve() not in {path.resolve() for path in src}:
        src.append(SERIAL_C)
    if RUNTIME_MCS51.resolve() not in {path.resolve() for path in inc}:
        inc.append(RUNTIME_MCS51)
    return tuple(src), tuple(inc)


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
    mounts: list[Path] | None = None,
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
    mount_list = list(mounts or [])
    if library is not None:
        mount_list.append(library)

    if sketch_mod.cxx_reason(sk.text):
        try:
            sk = cxxlower.lower_sketch(sk, mounts=mount_list or None)
        except cxxlower.CxxLowerError as exc:
            raise sketch_mod.cxx_error(sk, exc.hit, exc.detail) from exc

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
    sources = (sketch_unit, *sk.extra_c, *sk.extra_asm, *lib.sources)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in sources:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    defines = tuple(dict.fromkeys((*lib.defines, *sk.extra_defines, *extra_defines)))
    includes = list(lib.includes)
    for path in sk.extra_includes:
        if path not in includes:
            includes.append(path)
    includes = _with_sketch_dir(sk, includes)
    sources, includes_t = _link_serial(sk, tuple(unique), tuple(includes))
    return CompilePlan(
        board=board,
        sketch=sk,
        sources=sources,
        includes=includes_t,
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
        sources = [sk.path, *sk.extra_c, *sk.extra_asm]
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
            sources = [generated, *sk.extra_c, *sk.extra_asm, RUNTIME_C]
        else:
            sources = [sk.path, *sk.extra_c, *sk.extra_asm, RUNTIME_C]
        defines = ("ND_NIUS_SKETCH_MAIN", *extra_defines)
        runtime = "sketch"
        includes = [RUNTIME_MCS51]
    else:
        raise ValueError(
            f"{sk.path.name} has neither main() nor setup()/loop()"
        )

    includes = _with_sketch_dir(sk, includes)
    sources_t, includes_t = _link_serial(sk, tuple(sources), tuple(includes))
    return CompilePlan(
        board=board,
        sketch=sk,
        sources=sources_t,
        includes=includes_t,
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
    defines = list(plan.defines)
    if plan.board.family == "mcs51" and plan.board.f_cpu:
        osc = f"NIUS_FOSC={plan.board.f_cpu}UL"
        if osc not in defines:
            defines.append(osc)
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
        defines=defines,
    )


def upload_image(plan: CompilePlan, image: Path, *, skip_probe: bool = False,
                 hold_reset: bool = False) -> int:
    """Program *image* onto the planned board.

    With *hold_reset* the part is left in reset when programming finishes, so
    the caller can open the UART before `reset_board` starts it. Anything the
    sketch prints in its first milliseconds is otherwise lost while Windows
    is still opening the COM port.
    """

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
        hold_reset=hold_reset,
    )


def reset_board(plan: CompilePlan) -> None:
    """Take the board out of reset. Raises so a monitor hook can report it."""
    rc = flash.reset(target=plan.board.part, confirm=plan.board.part)
    if rc != 0:
        raise RuntimeError(f"reset failed with exit status {rc}")
