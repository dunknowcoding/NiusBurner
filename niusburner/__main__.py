"""NiusBurner command line.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

    python -m niusburner list                 what the registry knows about
    python -m niusburner detect               probe for what is really here
    python -m niusburner which <part>         how could I program this chip
    python -m niusburner flash <part> ...     do it

`detect` and `flash` are kept apart deliberately. Most failures on these parts
are environmental -- a compiler that was never installed, a programmer with no
driver, a 12 V rail that is not switching -- and finding that out during a
flash, halfway through erasing a chip, is the worst possible moment.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, registry


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


def _cmd_flash(args: argparse.Namespace) -> int:
    opts = [f for f in registry.programmers_for(args.part) if f.present]
    if not opts:
        print(f"no usable programmer for {args.part}.", file=sys.stderr)
        print("'python -m niusburner which %s' lists what would work and why "
              "it does not yet." % args.part, file=sys.stderr)
        return 1

    print("not implemented yet: no part has been flashed with this tool.",
          file=sys.stderr)
    print("The AT89C2051 path is closest -- see "
          "niusburner/targets/at89c2051_nano.py, which runs standalone today.",
          file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="niusburner",
        description="Build and flash firmware for parts the Arduino IDE cannot reach.")
    ap.add_argument("--version", action="version", version=f"niusburner {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="what the registry knows about").set_defaults(fn=_cmd_list)

    p = sub.add_parser("detect", help="probe for what is really installed")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero unless everything is present")
    p.set_defaults(fn=_cmd_detect)

    p = sub.add_parser("which", help="how could I program this part")
    p.add_argument("part")
    p.set_defaults(fn=_cmd_which)

    p = sub.add_parser("flash", help="write firmware to a part")
    p.add_argument("part")
    p.add_argument("image", nargs="?")
    p.add_argument("--port")
    p.set_defaults(fn=_cmd_flash)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
