"""NiusBurner command line.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

    python -m niusburner setup                what to install on this machine
    python -m niusburner boards               parts this tool knows how to flash
    python -m niusburner lower   <sketch>     BASIC Arduino C++ → C (no compile)
    python -m niusburner compile <sketch> --board at89s52
    python -m niusburner upload  <sketch> --board at89s52 --yes
    python -m niusburner upload  <sketch> --board at89s52 --yes --port COM31 --expect "NB TM1637"
    python -m niusburner monitor --port COM31 --baud 9600

Low-level commands (`build-mcs51`, `probe`, `flash`) stay available. The
commands above are the workflow: a sketch, a board, one compile, one flash.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__, boards as boards_mod, build, display as display_mod
from . import flash, registry, workflow
from .package import package_image, verify_package
from .progress import info, stage


def _cmd_list(args: argparse.Namespace) -> int:
    reg = registry.load_registry()
    print(f"toolchain root: {registry.toolchain_root(reg)}\n")

    print("compilers")
    for name, e in reg["compilers"].items():
        print(f"  {name:16} {', '.join(e.get('family', [])) or '-'}")

    print("\nprogrammers")
    for name, e in reg["programmers"].items():
        print(f"  {name:16} {', '.join(e.get('programs', [])) or '-'}")
    return 0


def _cmd_boards(args: argparse.Namespace) -> int:
    catalog = boards_mod.all_boards()
    width = max(len(b.id) for b in catalog.values())
    if getattr(args, "features", False):
        names = boards_mod.FEATURES
        print(f"  {'board':{width}}  " + "  ".join(f"{n:8}" for n in names))
        for board in catalog.values():
            cells = [f"{board.capability(name):8}" for name in names]
            print(f"  {board.id:{width}}  " + "  ".join(cells))
        print(
            "\n  hardware  the part has the peripheral"
            "\n  software  no peripheral, but NiusBurner bit-bangs it and the"
            "\n            matching Arduino facade works"
            "\n  none      neither, so a call that needs it is refused with"
            "\n            the reason instead of being silently retimed"
        )
        return 0
    for board in catalog.values():
        flash = f"{board.code_size // 1024} KB"
        print(
            f"  {board.id:{width}}  {flash:6}  {board.programmer:16}  "
            f"{board.status:12}  {board.note}"
        )
    print("\ncompile + flash:  python -m niusburner upload <sketch> --board at89s52 --yes")
    print("peripherals:      python -m niusburner boards --features")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    found = registry.scan()
    width = max(len(f.name) for f in found)

    ready = 0
    for f in found:
        mark = "ready  " if f.present else "MISSING"
        detail = f.where if f.present else f.reason
        print(f"  {mark}  {f.kind:10} {f.name:{width}}  {detail}")
        ready += f.present

    print(f"\n{ready}/{len(found)} present")

    if args.strict and ready != len(found):
        return 1
    return 0


def _print_check(ok: bool, name: str, detail: str) -> None:
    mark = "ready  " if ok else "MISSING"
    print(f"  {mark}  {name:16}  {detail}")


def _cmd_setup(args: argparse.Namespace) -> int:
    """Tell the user what to install so `upload` can run on this machine."""
    from . import config

    missing_required = 0
    for tool in sorted(config.TOOLS):
        given = getattr(args, tool, None)
        if given is None:
            continue
        try:
            written = config.set_tool(tool, given)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"recorded {tool} in {written}")
        print()
    board = boards_mod.get_board(args.board) if args.board else None

    print("compiler")
    sdcc = build.find_sdcc()
    if sdcc:
        try:
            banner = build._run([str(sdcc), "--version"], pathlib.Path.cwd()).splitlines()[0]
        except (OSError, ValueError) as exc:
            _print_check(False, "sdcc", str(exc))
            missing_required += 1
        else:
            _print_check(True, "sdcc", f"{sdcc}  ({banner})")
    else:
        _print_check(
            False, "sdcc",
            "not on PATH and not in Program Files. "
            "Install from https://sourceforge.net/projects/sdcc/files/",
        )
        missing_required += 1

    print("\ntool paths")
    for label, value in config.describe():
        print(f"  {label:20}  {value}")
    print("  record one with       python -m niusburner setup --sdcc <path>")

    print("\nprogrammer")
    hid_ok = True
    try:
        import hid  # noqa: F401
        _print_check(True, "hidapi", "python package")
    except ImportError:
        hid_ok = False
        _print_check(False, "hidapi", "pip install hidapi  (needed for USB-ISP HID)")

    found = {f.name: f for f in registry.scan()}
    want = [board.programmer] if board else ["usbisp_hid"]
    for name in want:
        entry = found.get(name)
        if entry is None:
            _print_check(False, name, "not in the toolchain registry")
            continue
        if entry.present:
            _print_check(True, name, entry.where or entry.version or "present")
        else:
            _print_check(False, name, entry.reason)
            install = (entry.meta or {}).get("install") or {}
            if install.get("note"):
                print(f"           {install['note']}")
            if install.get("url"):
                print(f"           {install['url']}")
            if (entry.meta or {}).get("wiring"):
                print(f"           wiring: {entry.meta['wiring']}")

    print("\nlibrary (optional, for NiusDisplay sketches)")
    lib = display_mod.find_niusdisplay(
        pathlib.Path(args.library) if args.library else None)
    if lib:
        _print_check(True, "NiusDisplay", str(lib))
    else:
        _print_check(
            False, "NiusDisplay",
            "not found. GPIO blink still works. For TM1637/OLED: "
            "pass --library or set NIUSDISPLAY",
        )

    print("\nArduino IDE")
    try:
        from . import ide as ide_mod
        dest = ide_mod.install_arduino_platform(
            pathlib.Path(args.sketchbook) if args.sketchbook else None)
        _print_check(True, "board package", str(dest))
        print("           Tools > Board > NiusBurner 8051 (SDCC) > AT89S52")
        print("           Tools > Programmer > USB-ISP HID (03EB:C8B4)")
        print("           Tools > Optimize / Debug info / Compiler")
        print("           Verify = SDCC; Upload = USB-ISP (erases the chip)")
        print("           .S tabs and SDCC __asm are assembled with sdas8051, not avr-as")
    except FileNotFoundError as exc:
        _print_check(False, "board package", str(exc))

    print()
    if board:
        print(f"board {board.id}: {board.note}")
        print(
            "next:  python -m niusburner upload examples/at89s52_blink "
            f"--board {board.id} --yes"
        )
    else:
        print("next:  python -m niusburner boards")
        print("       python -m niusburner setup --board at89s52")

    if not hid_ok and (board is None or board.programmer == "usbisp_hid"):
        missing_required += 1
    if args.strict and missing_required:
        return 1
    return 0 if missing_required == 0 else 1


def _cmd_which(args: argparse.Namespace) -> int:
    """
    Every way of programming a part, not one recommendation.

    An STC89C52RC can be written over SPI ISP with a USB-ISP *or* through its
    serial bootloader, and which is correct depends on how the board is wired.
    Picking one here would be guessing about a bench this program cannot see.
    """
    opts = registry.programmers_for(args.part)
    if not opts:
        print(f"no programmer in the registry claims {args.part}", file=sys.stderr)
        print("run 'python -m niusburner list' to see what is covered",
              file=sys.stderr)
        return 1

    for f in opts:
        print(f"{f.name}  [{f.status}]")
        if f.meta.get("note"):
            print(f"    {f.meta['note']}")
        if f.meta.get("wiring"):
            print(f"    wiring: {f.meta['wiring']}")
        if not f.present and f.reason:
            print(f"    not usable yet: {f.reason}")
        print()
    return 0


def _print_plan(plan: workflow.CompilePlan) -> None:
    """What is about to be built. Every line flushes.

    A plain print() is block-buffered once stdout is a pipe, which the
    Arduino IDE panel is, so unflushed lines surface after the upload they
    were supposed to introduce.
    """
    board = plan.board
    info(f"board     {board.id}  ({board.code_size} B flash, "
         f"{board.iram_size} B IRAM, {board.programmer})")
    info(f"sketch    {plan.sketch.path}")
    if plan.sketch.lowered:
        info("lowered   BASIC Arduino C++ -> C")
    info(f"runtime   {plan.runtime}"
         + (f"  ({plan.library})" if plan.library else ""))
    info(f"sources   {len(plan.sources)} translation units")
    if board.family == "mcs51":
        info(f"sdcc      --model-{plan.model}"
             + (" --stack-auto" if plan.stack_auto else "")
             + (f" --xram-size {plan.xram_size}" if plan.xram_size else ""))
    else:
        info(f"{board.compiler:9} -mcpu={board.part}")


def _plan_from_args(args: argparse.Namespace) -> workflow.CompilePlan:
    return workflow.plan_compile(
        args.sketch,
        args.board,
        library=args.library,
        mounts=args.mount,
        xram_size=args.xram_size,
        defines=args.define,
        output=args.output,
    )


def _cmd_compile(args: argparse.Namespace) -> int:
    try:
        plan = _plan_from_args(args)
        _print_plan(plan)
        output = args.output or workflow.default_output(plan.sketch, plan.board)
        result = workflow.compile_plan(
            plan, output, compiler=args.compiler,
            optimize=getattr(args, "optimize", "size"),
            debug_symbols=getattr(args, "debug_symbols", False))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"compile failed: {exc}", file=sys.stderr)
        return 2
    _print_usage(plan, result)
    info(f"image     {result.image}")
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    try:
        plan = _plan_from_args(args)
        _print_plan(plan)
        output = args.output or workflow.default_output(plan.sketch, plan.board)
        result = workflow.compile_plan(
            plan, output, compiler=args.compiler,
            optimize=getattr(args, "optimize", "size"),
            debug_symbols=getattr(args, "debug_symbols", False))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"compile failed: {exc}", file=sys.stderr)
        return 2
    _print_usage(plan, result)
    info(f"image     {result.image}")

    if not args.yes:
        print(
            f"\nRefusing to erase {plan.board.part} without --yes.\n"
            f"  python -m niusburner upload {plan.sketch.directory} "
            f"--board {plan.board.id} --yes",
            file=sys.stderr,
        )
        return 2

    port = getattr(args, "port", None)
    # A part on the ISP header can be held in reset until the monitor has the
    # UART open, because the programmer owns its reset line. A part with a
    # serial bootloader cannot: the bootloader starts the firmware itself,
    # and the port it starts on is the one being programmed through.
    holds_reset = plan.board.programmer != "stcgal"
    try:
        rc = workflow.upload_image(
            plan, result.image,
            hold_reset=bool(port) and holds_reset,
            port=port or "")
    except (OSError, ValueError) as exc:
        print(f"upload failed: {exc}", file=sys.stderr)
        return 2
    if rc != 0:
        return rc
    if not port:
        return 0
    from . import monitor as monitor_mod
    baud = args.baud
    if baud is None:
        baud = monitor_mod.uart_baud_from_sketch(plan.sketch.text) or 115200
    return monitor_mod.monitor(
        port,
        baud,
        seconds=args.seconds if args.seconds is not None else 4.0,
        expect=args.expect,
        on_open=(lambda: workflow.reset_board(plan)) if holds_reset else None,
    )


def _cmd_probe(args: argparse.Namespace) -> int:
    try:
        return flash.probe(target=args.target, confirm=args.confirm)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


def _cmd_flash(args: argparse.Namespace) -> int:
    try:
        return flash.burn(target=args.target, image=args.image,
                             confirm=args.confirm,
                             state_policy=args.state_policy,
                             address=args.address, config=args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


def _cmd_lower(args: argparse.Namespace) -> int:
    from . import cxxlower
    argv = [str(args.sketch)]
    if args.output is not None:
        argv.extend(["-o", str(args.output)])
    for mount in args.mount or []:
        argv.extend(["--mount", str(mount)])
    argv.extend(["--board", args.board])
    return cxxlower.main(argv)


def _cmd_monitor(args: argparse.Namespace) -> int:
    from . import monitor as monitor_mod
    return monitor_mod.monitor(
        args.port, args.baud, seconds=args.seconds, expect=args.expect)


def _cmd_package(args: argparse.Namespace) -> int:
    try:
        manifest = package_image(args.image, args.output, target=args.target,
                                 load_address=args.address)
        verify_package(manifest)
    except (OSError, ValueError) as exc:
        print(f"package failed: {exc}", file=sys.stderr)
        return 2
    print(manifest)
    return 0


def _cmd_build_mcs51(args: argparse.Namespace) -> int:
    try:
        result = build.build_mcs51(
            args.source, args.include, args.output,
            compiler=args.compiler, contract=args.contract,
            code_size=args.code_size, iram_size=args.iram_size,
            program_limit=args.program_limit, data_limit=args.data_limit,
            require_version=args.require_version,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 2
    print(result.manifest)
    print(f"program: {result.program_bytes} bytes")
    if result.kernel_data_bytes is not None:
        print(f"kernel data: {result.kernel_data_bytes} bytes")
    return 0


def _print_usage(plan, result) -> None:
    """What the image cost, against what the part actually has.

    The units differ by family and saying so matters: a PIC16 instruction is
    one 14-bit word, so quoting bytes there would be wrong by more than a
    factor of two.
    """
    board = plan.board
    if board.family == "pic16":
        words = result.program_words
        stage(int(100 * words / board.code_size), "Flash",
              f"{words}/{board.code_size} words")
        stage(int(100 * result.data_bytes / board.iram_size), "RAM",
              f"{result.data_bytes}/{board.iram_size} B")
        if result.eeprom_bytes:
            info(f"eeprom    {result.eeprom_bytes} B")
    else:
        rom = result.program_bytes
        stage(int(100 * rom / board.code_size), "Flash",
              f"{rom}/{board.code_size} B")
        if result.iram_bytes:
            iram = result.iram_bytes
            stage(int(100 * iram / board.iram_size), "IRAM",
                  f"{iram}/{board.iram_size} B  "
                  f"{result.stack_bytes} B left for the stack")
        if result.xram_bytes:
            info(f"xram      {result.xram_bytes} B / {plan.xram_size} B")
    if result.optimize != "size":
        info(f"optimize  {result.optimize}")
    if result.symbols:
        info(f"symbols   {len(result.symbols)} file(s) in {result.image.parent}")


def _add_sketch_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("sketch", type=pathlib.Path,
                        help="`.ino`, `.c`, or a sketch directory")
    parser.add_argument("--board", required=True,
                        help="target board (see `niusburner boards`)")
    parser.add_argument("--library", type=pathlib.Path,
                        help="NiusDisplay root, if the sketch uses it")
    parser.add_argument("--mount", action="append", type=pathlib.Path, default=[],
                        help="library root with niusburner/adapter.json; repeatable")
    parser.add_argument("--output", type=pathlib.Path,
                        help="build directory (default: <sketch>/.niusburner/<board>)")
    parser.add_argument("--compiler", type=pathlib.Path)
    parser.add_argument("--xram-size", type=int,
                        help="external RAM in bytes; required for graphics on 8051")
    parser.add_argument("--define", action="append", default=[],
                        help="extra -DNAME[=VALUE]; repeatable")
    parser.add_argument("--optimize", choices=("size", "speed", "none"),
                        default="size",
                        help="what SDCC spends its effort on (default: size, "
                             "because flash runs out before cycles do)")
    parser.add_argument("--debug-symbols", action="store_true",
                        help="emit the symbol database and keep the listings, "
                             "so an image can be read back against its source")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="niusburner",
        description=(
            "Compile Arduino-shaped sketches and flash them onto parts "
            "the Arduino IDE cannot reach."
        ),
    )
    ap.add_argument("--version", action="version", version=f"niusburner {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="what to install so upload can run here")
    p.add_argument("--board", help="check the tools that board needs")
    p.add_argument("--library", type=pathlib.Path)
    p.add_argument("--sketchbook", type=pathlib.Path,
                   help="Arduino sketchbook to install the 8051 board package into")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero if a required tool is missing")
    p.add_argument("--sdcc", type=pathlib.Path,
                   help="record where SDCC is, for when PATH is not the "
                        "answer and the Arduino IDE cannot ask")
    p.add_argument("--xc8", type=pathlib.Path,
                   help="record where the XC8 driver (xc8-cc) is, for PIC "
                        "boards")
    p.add_argument("--pickit3", type=pathlib.Path,
                   help="record where ipecmd is -- the command-line "
                        "programmer that drives a PICkit 3")
    p.set_defaults(fn=_cmd_setup)

    p = sub.add_parser("boards", help="parts this tool can compile (and flash)")
    p.add_argument("--features", action="store_true",
                   help="show which peripherals each board has, and which "
                        "NiusBurner bit-bangs for it")
    p.set_defaults(fn=_cmd_boards)

    p = sub.add_parser(
        "lower",
        help="rewrite BASIC Arduino C++ to C that SDCC can compile",
    )
    p.add_argument("sketch", type=pathlib.Path,
                   help="`.ino`, `.c`, or a sketch directory")
    p.add_argument("-o", "--output", type=pathlib.Path,
                   help="write C to this file (default: stdout)")
    p.add_argument("--mount", action="append", type=pathlib.Path, default=[],
                   help="library root with niusburner/adapter.json; repeatable")
    p.add_argument("--board", default="at89s52",
                   help="target board, so a refusal can name the missing "
                        "peripheral (default: at89s52)")
    p.set_defaults(fn=_cmd_lower)

    p = sub.add_parser("compile", help="build a sketch for a board; do not flash")
    _add_sketch_flags(p)
    p.set_defaults(fn=_cmd_compile)

    p = sub.add_parser("upload", help="compile, then erase/program/verify")
    _add_sketch_flags(p)
    p.add_argument("--yes", action="store_true",
                   help="acknowledge that the chip will be erased")
    p.add_argument(
        "--port",
        help="after a verified flash, read UART on this CH341 port (COM31)",
    )
    p.add_argument(
        "--baud",
        type=int,
        default=None,
        help="UART baud after flash (default: Serial.begin in the sketch, else 115200)",
    )
    p.add_argument("--seconds", type=float, default=4.0,
                   help="UART listen seconds after flash (default 4)")
    p.add_argument(
        "--expect",
        help="fail unless this ASCII substring appears on the UART",
    )
    p.set_defaults(fn=_cmd_upload)

    p = sub.add_parser(
        "monitor",
        help="read the AT89S52 UART (CH341); not the USB-ISP HID dongle",
    )
    p.add_argument("--port", required=True,
                   help="host COM port of the CH341 (this bench: COM31)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--seconds", type=float,
                   help="exit after this many seconds (default: until Ctrl+C)")
    p.add_argument(
        "--expect",
        help="fail unless this ASCII substring appears (use after a verified ISP flash)",
    )
    p.set_defaults(fn=_cmd_monitor)

    sub.add_parser("list", help="what the registry knows about").set_defaults(fn=_cmd_list)

    p = sub.add_parser("detect", help="probe for what is really installed")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero unless everything is present")
    p.set_defaults(fn=_cmd_detect)

    p = sub.add_parser("which", help="how could I program this part")
    p.add_argument("part")
    p.set_defaults(fn=_cmd_which)

    p = sub.add_parser("package", help="create a reproducible image package")
    p.add_argument("target")
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("output", type=pathlib.Path)
    p.add_argument("--address", type=lambda value: int(value, 0), default=0)
    p.set_defaults(fn=_cmd_package)

    p = sub.add_parser(
        "build-mcs51",
        help="compile freestanding C through size-optimized 8051 assembly")
    p.add_argument("--source", action="append", type=pathlib.Path,
                   required=True, help="C source; repeat in link order")
    p.add_argument("--include", action="append", type=pathlib.Path, default=[],
                   help="include directory; repeat as needed")
    p.add_argument("--output", type=pathlib.Path, required=True)
    p.add_argument("--compiler", type=pathlib.Path)
    p.add_argument("--contract", type=pathlib.Path,
                   help="bounded generated receipt supplying program/data limits")
    p.add_argument("--code-size", type=int, default=2048)
    p.add_argument("--iram-size", type=int, default=128)
    p.add_argument("--program-limit", type=int)
    p.add_argument("--data-limit", type=int)
    p.add_argument("--require-version")
    p.set_defaults(fn=_cmd_build_mcs51)

    p = sub.add_parser("probe", help="read the chip signature; no erase")
    p.add_argument("target")
    p.add_argument("--confirm", required=True)
    p.set_defaults(fn=_cmd_probe)

    p = sub.add_parser("flash", help="erase, program and verify a ready image")
    p.add_argument("target")
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--confirm", required=True)
    p.add_argument("--ack-data-loss", action="store_true", required=True)
    p.add_argument("--state-policy", choices=("replace", "restore"), required=True)
    p.add_argument("--address", type=lambda value: int(value, 0), default=0)
    p.add_argument("--config", type=pathlib.Path)
    p.set_defaults(fn=_cmd_flash)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
