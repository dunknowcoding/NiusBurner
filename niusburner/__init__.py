"""NiusBurner - compile sketches and flash parts Arduino cannot reach.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Package layout, from the user inward:

    __main__.py     CLI (setup, boards, compile, upload, lower, …)
    workflow.py     choose board, wrap sketch, compile, flash
    cxxlower.py     BASIC Arduino C++ → C for SDCC
    sketch.py       .ino as C; real C++ still refused
    monitor.py      CH341 UART console (not the ISP dongle)
    display.py      locate NiusDisplay without importing it
    boards.py       named parts
    build.py        SDCC driver
    flash.py        delegate probe/burn to the programmer backend
    backends/       USB-ISP HID
    runtime/        GPIO runtime when NiusDisplay is not used
    registry.py     what is actually installed
"""

__version__ = "0.5.0"
