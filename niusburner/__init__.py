"""NiusBurner - compile sketches and flash parts Arduino cannot reach.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Package layout, from the user inward:

    __main__.py     CLI (setup, boards, compile, upload, …)
    workflow.py     choose board, wrap sketch, compile, flash
    sketch.py       .ino as C; refuse C++
    display.py      locate NiusDisplay without importing it
    boards.py       named parts
    build.py        SDCC driver
    flash.py        delegate probe/burn — not a debugger
    backends/       USB-ISP HID
    runtime/        GPIO runtime when NiusDisplay is not used
    registry.py     what is actually installed
"""

__version__ = "0.3.0"
