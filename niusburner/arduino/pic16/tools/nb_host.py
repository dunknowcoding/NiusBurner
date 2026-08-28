"""Arduino recipe host. Invoked by platform.txt; must stay import-light at start.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

The IDE runs this from the sketchbook, with a working directory of its own
choosing, so neither the interpreter that has `niusburner` nor the directory
it lives in can be assumed. `niusburner setup` records both next to this
file, and they are used only as a fallback: an installed package on the
current interpreter wins.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_PY_PATH = _TOOLS / "python.path"
_PKG_PATH = _TOOLS / "niusburner.path"


def _python() -> None:
    """Re-exec under the interpreter `niusburner setup` recorded, if needed."""
    if not _PY_PATH.is_file():
        return
    recorded = _PY_PATH.read_text(encoding="utf-8").strip()
    if not recorded:
        return
    current = Path(sys.executable).resolve()
    try:
        want = Path(recorded).resolve()
    except OSError:
        return
    if current == want or not want.is_file():
        return
    import os
    os.execv(str(want), [str(want), str(Path(__file__).resolve()), *sys.argv[1:]])


def _package() -> None:
    """Put the recorded package directory on sys.path if the import fails."""
    try:
        import niusburner  # noqa: F401
        return
    except ImportError:
        pass
    if not _PKG_PATH.is_file():
        return
    recorded = _PKG_PATH.read_text(encoding="utf-8").strip()
    if recorded and Path(recorded).is_dir():
        sys.path.insert(0, recorded)


def _fail(message: str) -> int:
    sys.stderr.write(
        "niusburner: " + message + "\n"
        "  Run `python -m niusburner setup` from the NiusBurner checkout to\n"
        "  re-record this machine's interpreter and package location.\n")
    return 2


if __name__ == "__main__":
    _python()
    _package()
    try:
        from niusburner.ide import arduino_main
    except ImportError as exc:
        raise SystemExit(_fail(f"cannot import the niusburner package ({exc})"))
    raise SystemExit(arduino_main(sys.argv[1:]))
