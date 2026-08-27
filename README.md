# NiusBurner

Compile Arduino-shaped sketches and flash them onto parts the Arduino IDE
cannot reach.

NiusDisplay is a **plain Arduino library**. Programmers, 12 V rails, Intel HEX,
ISP wiring and SDCC live here so that library can stay installable through
the Library Manager. NiusBurner never imports NiusDisplay; it finds the tree
when a sketch names it.

## Quick start

```bash
python -m niusburner setup --board at89s52
python -m niusburner upload examples/at89s52_blink --board at89s52 --yes
```

That is the whole happy path: install a compiler on this machine, write a
sketch that looks like Arduino (`setup` / `loop`), one command to compile and
burn. Details: [docs/workflow.md](docs/workflow.md).

## Layout

```
examples/            target sketches (the MCU you are flashing)
hardware/            firmware for programmer appliances we build
  nano_at89c2051/    Nano as a 12 V parallel programmer — not a target sketch
docs/
  workflow.md        the user path
  families/          per-family programming and wiring
niusburner/          the Python package
  __main__.py        CLI
  workflow.py        compile + upload
  sketch.py          .ino wrapping; honest C++ refusal
  display.py         find NiusDisplay, pick C sources
  boards.py          named parts (flash size, programmer)
  build.py           SDCC driver
  flash.py           delegate probe/burn to the programmer backend
  backends/          USB-ISP HID and later transports
  runtime/mcs51/     GPIO runtime for sketches that do not use NiusDisplay
tests/               host tests; no hardware required
```

Two kinds of `.ino` live in this repository and they are not interchangeable:

| Tree | Runs on | What it is | Flashed with |
|---|---|---|---|
| `examples/` | AT89S52 (the chip in the socket) | your sketch | `python -m niusburner upload` |
| `hardware/` | Arduino Nano (the programmer box) | 12 V parallel programmer firmware | `arduino-cli` onto the **Nano** |

`hardware/nano_at89c2051/nano_at89c2051.ino` is not an AT89C2051 program. The
2051 has no ISP; the Nano *is* the programmer. Details: [hardware/README.md](hardware/README.md).

## Status

- `verified` — run end to end on the bench
- `implemented` — tested against a host stub, not silicon
- `planned` — documented, not written

| Target | Method | Status |
|---|---|---|
| AT89S52 | USB-ISP HID | `verified` — probe `1E 52 06`, erase/program/verify/run |
| AT89C2051 | Nano-hosted 12 V programmer | `implemented`; physical backend pending |
| STC89C52RC | UART bootloader (`stcgal`) | `planned`; SPI ISP is the wrong protocol |
| STC15W408AS | `stcgal` serial bootloader | `planned` |
| PIC12F675 / PIC16F877A | PICkit 3 | `planned` |

## What it is not

**It does not vendor toolchains.** `EMBD_TOOLCHAINS` is an **environment
variable** naming a directory on this machine (default
`~/.local/share/niusburner/toolchains`). Compilers are never committed here.
SDCC for AT89S52 is found on PATH / Program Files, not under that variable.
See [docs/toolchains.md](docs/toolchains.md). `setup` / `detect` say which
tool is missing and where to get it.

**It does not compile Arduino C++ on SDCC.** SDCC has no C++ mode. A sketch
that `#include <NiusDisplay.h>` is refused; rewrite it against NiusDuino / the
C drivers, or use NiusDisplay's IAR 8051 Arduino core.

## Guides

- [docs/workflow.md](docs/workflow.md) — setup, compile, upload, NiusDisplay
- [docs/families/8051.md](docs/families/8051.md) — AT89S52, AT89C2051, STC
- [docs/families/pic.md](docs/families/pic.md) — PIC12F675, PIC16F877A
- [docs/toolchains.md](docs/toolchains.md) — why nothing is vendored
- [docs/integration.md](docs/integration.md) — using NiusBurner from another project
- [hardware/nano_at89c2051/](hardware/nano_at89c2051/) — building the 12 V programmer

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Third-party toolchains are **not** covered by that licence and are **not**
distributed here; each is fetched from its own vendor under its own terms.
