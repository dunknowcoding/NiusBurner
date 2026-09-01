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

import re
from dataclasses import dataclass
from pathlib import Path

from . import boards as boards_mod
from . import build, cxxlower, display as display_mod, flash, sketch as sketch_mod
from .boards import Board
from .build import Mcs51Build
from .display import DisplayLib
from .sketch import ARDUINO_MCS51, ARDUINO_PIC16, Sketch, runtime_dir

RUNTIME_HEADER = "nius_sketch.h"
#: Every family names its core unit the same, under its own directory.
RUNTIME_UNIT = "nius_sketch.c"

#: Arduino facades that lower to a C unit in adapters/Arduino/mcs51. A unit is
#: linked only when the lowered text actually calls into it, so a sketch that
#: never touches a bus does not pay for one.
RUNTIME_UNITS = (
    (("nius_serial_",), "nius_serial.c"),
    (("nius_wire_",), "nius_wire.c"),
    (("nius_spi_",), "nius_spi.c"),
    (("map", "shiftOut", "shiftIn", "random", "randomSeed", "randomRange"),
     "nius_extra.c"),
)


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


def _link_runtime(
    sk: Sketch,
    sources: tuple[Path, ...],
    includes: tuple[Path, ...],
    family: str = "mcs51",
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Add the Arduino API units the lowered sketch actually calls."""
    def names(token: str) -> bool:
        # A token ending in `_` is a prefix (nius_serial_begin, ...); anything
        # else is a whole identifier, so a sketch variable called `mapping`
        # does not drag in map().
        pattern = r"\b" + token if token.endswith("_") else r"\b" + token + r"\b"
        return bool(re.search(pattern, sk.text))

    wanted = [
        runtime_dir(family) / unit
        for tokens, unit in RUNTIME_UNITS
        if any(names(token) for token in tokens)
    ]
    if not wanted:
        return sources, includes
    src = list(sources)
    inc = list(includes)
    seen = {path.resolve() for path in src}
    for path in wanted:
        if path.resolve() not in seen:
            src.append(path)
            seen.add(path.resolve())
    home = runtime_dir(family)
    if home.resolve() not in {path.resolve() for path in inc}:
        inc.append(home)
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
    #: Families whose Arduino runtime and compiler are both wired up.
    if board.family not in sketch_mod.ARDUINO_RUNTIME:
        raise ValueError(
            f"board {board.id} is {board.compiler}/{board.family}, and there "
            f"is no Arduino runtime for that family yet. Known: "
            f"{', '.join(sorted(sketch_mod.ARDUINO_RUNTIME))}."
        )
    sk = sketch_mod.resolve_sketch(sketch_path)
    out = (output or default_output(sk, board)).resolve()
    mount_list = list(mounts or [])
    if library is not None:
        mount_list.append(library)

    try:
        if sketch_mod.cxx_reason(sk.text):
            sk = cxxlower.lower_sketch(
                sk, mounts=mount_list or None, board=board)
        else:
            # Not C++, but still an Arduino sketch: the board checks and the
            # API rewrites apply either way.
            sk = cxxlower.check_sketch(sk, board=board)
    except cxxlower.CxxLowerError as exc:
        raise sketch_mod.cxx_error(
            sk, exc.hit, exc.detail, kind=exc.kind) from exc

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
    sources, includes_t = _link_runtime(sk, tuple(unique), tuple(includes), board.family)
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
            sources = [generated, *sk.extra_c, *sk.extra_asm,
                       runtime_dir(board.family) / RUNTIME_UNIT]
        else:
            sources = [sk.path, *sk.extra_c, *sk.extra_asm,
                       runtime_dir(board.family) / RUNTIME_UNIT]
        defines = ("ND_NIUS_SKETCH_MAIN", *extra_defines)
        runtime = "sketch"
        includes = [runtime_dir(board.family)]
    else:
        raise ValueError(
            f"{sk.path.name} has neither main() nor setup()/loop()"
        )

    includes = _with_sketch_dir(sk, includes)
    sources_t, includes_t = _link_runtime(sk, tuple(sources), tuple(includes), board.family)
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


#: Extra units linked by a build option rather than by what a sketch names.
OPTION_UNITS = {"isp_entry": "nius_ispentry.c"}


_INTERRUPT_HANDLER = re.compile(
    r"\bvoid\s+([A-Za-z_]\w*)\s*\(\s*(?:void)?\s*\)\s*"
    r"__interrupt\s*\(\s*(\d+)\s*\)\s*\{"
)


def _runtime_with_sketch_vectors(
    plan: CompilePlan,
    output: Path,
    sources: list[Path],
    *,
    isp_entry: bool,
) -> list[Path]:
    """Put sketch ISR prototypes beside main() so SDCC emits their vectors.

    SDCC only creates an MCS-51 vector for handlers declared in the
    translation unit that owns main(). Arduino-shaped sketches keep main() in
    nius_sketch.c, so merely defining an ISR in sketch.c compiles its body but
    previously left the corresponding silicon vector empty.
    """
    if plan.board.family != "mcs51" or plan.runtime != "sketch":
        return sources
    handlers = [
        (name, int(vector))
        for name, vector in _INTERRUPT_HANDLER.findall(
            cxxlower._code_words(plan.sketch.text))
    ]
    if not handlers:
        return sources
    vectors: dict[int, str] = {}
    for name, vector in handlers:
        if vector > 5:
            raise ValueError(f"AT89S52 interrupt vector {vector} is outside 0..5")
        if vector in vectors:
            raise ValueError(
                f"interrupt vector {vector} is defined by both "
                f"{vectors[vector]} and {name}")
        vectors[vector] = name
    if isp_entry and 4 in vectors:
        raise ValueError(
            "interrupt vector 4 is already used by the optional UART "
            "bootloader-entry handler")

    runtime = (runtime_dir(plan.board.family) / RUNTIME_UNIT).resolve()
    if runtime not in {source.resolve() for source in sources}:
        return sources
    wrapper = output / "nius_sketch_vectors.c"
    declarations = "".join(
        f"void {name}(void) __interrupt({vector});\n"
        for name, vector in sorted(handlers, key=lambda item: item[1])
    )
    wrapper.write_text(
        "/* Generated: sketch interrupt declarations must share main(). */\n"
        + declarations
        + runtime.read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    return [wrapper if source.resolve() == runtime else source for source in sources]


def compile_plan(
    plan: CompilePlan,
    output: Path,
    *,
    compiler: Path | None = None,
    optimize: str = "size",
    isp_entry: bool = False,
) -> Mcs51Build:
    output.mkdir(parents=True, exist_ok=True)
    if plan.generated is not None:
        header = "NiusDuino.h" if plan.runtime == "niusdisplay" else RUNTIME_HEADER
        sketch_mod.wrap_ino(plan.sketch, plan.generated, runtime_header=header)
    defines = list(plan.defines)
    sources = list(plan.sources)
    if isp_entry:
        if plan.board.family != "mcs51":
            raise ValueError(
                "bootloader entry over the UART is an STC feature; "
                f"{plan.board.id} is {plan.board.family}")
        defines.append("NIUS_ISP_ENTRY")
        defines.append(f"NIUS_ISP_CONTR_ADDR=0x{plan.board.isp_contr:02X}")
        unit = runtime_dir(plan.board.family) / OPTION_UNITS["isp_entry"]
        if unit not in sources:
            sources.append(unit)
    if plan.board.is_pic:
        # Which ports the package brings out: naming a port the part does
        # not have is a compile error, not a dead store.
        omitted = [f"NIUS_PIC_CFG_{name.upper()}=0"
                   for name in plan.board.config_omit]
        for macro in (f"NIUS_PIC_PORTS={plan.board.ports}",
                      f"NIUS_PIC_ANALOG={plan.board.analog}",
                      f"NIUS_PIC_USART={plan.board.usart}",
                      f"NIUS_PIC18_CONFIG={plan.board.config_profile}",
                      f"NIUS_PIC_GPIO_STYLE={1 if plan.board.gpio_style else 0}",
                      f"NIUS_PIC_OSC_INTERNAL={plan.board.internal_osc}",
                      *omitted):
            if macro not in defines:
                defines.append(macro)
    if plan.board.is_pic24:
        # Ports are named rather than counted here, so the runtime gets a
        # mask: a dsPIC30F4013 has A, B, C, D and F, with no E.
        for macro in (f"NIUS_PIC24_PORTS=0x{plan.board.port_mask:02X}",
                      f"NIUS_PIC24_CONFIG={plan.board.config_profile}"):
            if macro not in defines:
                defines.append(macro)
    if plan.board.family == "mcs51":
        # A part with no Timer 2 must not have the Timer 2 baud generator
        # compiled in: those SFR addresses simply are not there.
        # The 1T generations select UART1's clock source in AUXR, and it
        # does not come up pointing at Timer 1. Without this the reload is
        # written and then ignored, which looks like a wiring fault.
        auxr = 1 if plan.board.protocol.startswith(("stc15", "stc8")) else 0
        for macro in (f"NIUS_HAS_TIMER2={1 if plan.board.timer2 else 0}",
                      f"NIUS_UART_AUXR={auxr}",
                      f"NIUS_CLOCKS_PER_MC={plan.board.clocks_per_mc}UL"):
            if macro not in defines:
                defines.append(macro)
    if plan.board.family == "mcs51" and plan.board.f_cpu:
        osc = f"NIUS_FOSC={plan.board.f_cpu}UL"
        if osc not in defines:
            defines.append(osc)
    sources = _runtime_with_sketch_vectors(
        plan, output, sources, isp_entry=isp_entry)
    if plan.board.is_pic24:
        from . import build_pic24

        return build_pic24.build_pic24(
            sources,
            list(plan.includes),
            output,
            compiler=compiler,
            part=plan.board.part,
            family=plan.board.family,
            f_cpu=plan.board.f_cpu,
            program_size=plan.board.code_size,
            data_size=plan.board.iram_size,
            defines=defines,
            optimize=optimize,
        )
    if plan.board.is_pic:
        from . import build_pic

        return build_pic.build_pic(
            sources,
            list(plan.includes),
            output,
            compiler=compiler,
            part=plan.board.part,
            f_cpu=plan.board.f_cpu,
            family=plan.board.family,
            program_size=plan.board.code_size,
            data_size=plan.board.iram_size,
            defines=defines,
            optimize=optimize,
        )
    return build.build_mcs51(
        sources,
        list(plan.includes),
        output,
        compiler=compiler,
        code_size=plan.board.code_size,
        iram_size=plan.board.iram_size,
        model=plan.model,
        stack_auto=plan.stack_auto,
        xram_size=plan.xram_size,
        defines=defines,
        optimize=optimize,
    )


def upload_image(plan: CompilePlan, image: Path, *,
                 hold_reset: bool = False, port: str = "",
                 reset_pin: str = "") -> int:
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
    # No pre-probe. `burn` opens its own ISP session and checks the
    # signature before it erases anything, so probing first only costs a
    # second round trip and puts a stray line above the banner.
    return flash.burn(
        target=board.part,
        image=image,
        confirm=board.part,
        programmer=board.programmer,
        port=port,
        reset_pin=reset_pin,
        state_policy="replace",
        hold_reset=hold_reset,
    )


def reset_board(plan: CompilePlan) -> None:
    """Take the board out of reset. Raises so a monitor hook can report it."""
    rc = flash.reset(target=plan.board.part, confirm=plan.board.part)
    if rc != 0:
        raise RuntimeError(f"reset failed with exit status {rc}")
