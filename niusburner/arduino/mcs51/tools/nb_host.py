"""Arduino recipe host. Invoked by platform.txt; must stay import-light at start."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_PY_PATH = _TOOLS / "python.path"


def _python() -> None:
    """Re-exec under the interpreter `niusburner setup` recorded, if needed."""
    if not _PY_PATH.is_file():
        return
    recorded = _PY_PATH.read_text(encoding="utf-8").strip()
    if not recorded:
        return
    current = Path(sys.executable).resolve()
    want = Path(recorded).resolve()
    if current == want:
        return
    import os
    os.execv(str(want), [str(want), str(Path(__file__).resolve()), *sys.argv[1:]])


if __name__ == "__main__":
    _python()
    from niusburner.ide import arduino_main
    raise SystemExit(arduino_main(sys.argv[1:]))
