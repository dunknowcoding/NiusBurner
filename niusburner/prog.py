"""niusprog — physical programming backend invoked by `niusburner flash`.

Accepted sub-commands (as specified by niusburner/flash.py):
  burn <target> <image.ihx> --addr <hex> --confirm <target>
       --ack-data-loss --state-policy replace

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import argparse
import pathlib
import sys


def _cmd_probe(args: argparse.Namespace) -> int:
    if args.confirm != args.target:
        print("refused: --confirm must match target", file=sys.stderr)
        return 2
    from niusburner.backends.usbisp_hid import probe
    return probe(args.target)


def _cmd_burn(args: argparse.Namespace) -> int:
    if args.confirm != args.target:
        print("refused: --confirm must match target", file=sys.stderr)
        return 2

    image = pathlib.Path(args.image)
    if not image.is_file():
        print(f"refused: image not found: {image}", file=sys.stderr)
        return 2

    # Programmer selection is automatic for now (only one backend supported).
    from niusburner.backends.usbisp_hid import flash
    return flash(image, args.target, run=not args.hold_reset)


def _cmd_reset(args: argparse.Namespace) -> int:
    if args.confirm != args.target:
        print("refused: --confirm must match target", file=sys.stderr)
        return 2
    from niusburner.backends.usbisp_hid import reset
    return reset(args.target)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="niusprog",
        description="Physical programming backend for NiusBurner.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("burn")
    p.add_argument("target")
    p.add_argument("image")
    p.add_argument("--addr", default="0x0")
    p.add_argument("--confirm", required=True)
    p.add_argument("--ack-data-loss", action="store_true", required=True)
    p.add_argument("--state-policy", choices=("replace", "restore"), required=True)
    p.add_argument("--hold-reset", action="store_true",
                   help="leave the part in reset so a caller can attach to "
                        "its UART before the first instruction runs")
    p.set_defaults(fn=_cmd_burn)

    p4 = sub.add_parser("reset")
    p4.add_argument("target")
    p4.add_argument("--confirm", required=True)
    p4.set_defaults(fn=_cmd_reset)

    p3 = sub.add_parser("probe")
    p3.add_argument("target")
    p3.add_argument("--confirm", required=True)
    p3.set_defaults(fn=_cmd_probe)

    # recover sub-command (stub — restore not yet implemented)
    p2 = sub.add_parser("recover")
    p2.add_argument("target")
    p2.add_argument("--confirm", required=True)
    p2.add_argument("--ack-data-loss", action="store_true", required=True)
    p2.add_argument("--state-policy")
    p2.add_argument("--backup")
    p2.set_defaults(fn=lambda a: (
        print("recover: not yet implemented", file=sys.stderr), 2)[1])

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
