# Workflow

NiusBurner is the legacy-MCU half of NiusDisplay: write an Arduino-shaped
sketch, install a compiler on this machine, compile and flash with one CLI.
NiusDisplay stays a plain Arduino library. This tool never imports it.

```text
  .ino / .c          NiusBurner CLI           silicon
  (your sketch)  →   setup / compile / upload  →  AT89S52 over USB-ISP
                         │
                         ├── SDCC on PATH (or Program Files)
                         ├── NiusDisplay tree, if the sketch names it
                         └── USB-ISP HID (VID 03EB / PID C8B4)
```

## Once per machine

```bash
python -m niusburner setup --board at89s52
```

That is a checklist, not an installer. Missing SDCC, `hidapi`, or the dongle
are reported with the URL or `pip` line that fixes them. A NiusDisplay
checkout next to this repo is optional and detected automatically.

Install SDCC from https://sourceforge.net/projects/sdcc/files/ so `sdcc` is
on PATH (the Windows installer also lands at `C:\Program Files\SDCC\bin`).
That path is **not** `EMBD_TOOLCHAINS`. `EMBD_TOOLCHAINS` is an environment
variable for portable vendor trees (XC8, …); default and how to set it are
in [toolchains.md](toolchains.md).

```bash
pip install hidapi
```

## Every sketch

```bash
python -m niusburner compile examples/at89s52_blink --board at89s52
python -m niusburner upload  examples/at89s52_blink --board at89s52 --yes
```

`upload` compiles, reads the signature, then erases, programs and verifies.
`--yes` is the erase acknowledgement. Without it the image is still built.

`--board` fills in flash size, IRAM, compiler flags and programmer. Run
`python -m niusburner boards` for the list.

## What a sketch is allowed to be

| Kind | Example | SDCC |
|---|---|---|
| C-shaped `.ino` with `setup()` / `loop()` | `examples/at89s52_blink` | yes — wrapped with a tiny GPIO runtime |
| C `.c` with `main()` | any freestanding file | yes |
| NiusDuino C (NiusDisplay C API) | `examples/niusdisplay_tm1637` | yes — HAL + named drivers only |
| Arduino C++ (`#include <NiusDisplay.h>`, `Serial`, classes) | NiusDisplay `examples/*.ino` | **no** — refused, with a pointer to the C API or the IAR core |

SDCC has no C++ mode. Pretending otherwise would compile-fail in the worst
place. The Arduino C++ sketches keep working on AVR/ESP via the Arduino IDE;
on an 8051 they become NiusDuino C, or they use NiusDisplay's IAR Arduino core.

## NiusDisplay

Point at the library if it is not a sibling of this repo:

```bash
python -m niusburner upload examples/niusdisplay_tm1637 --board at89s52 \
  --library G:\Arduino\driver\NiusDisplay --yes
```

Or set `NIUSDISPLAY`. Drivers are inferred from `#include`; SDCC has no
`--gc-sections`, so only those translation units are linked.

A minimum AT89S52 DIP-40 has **no external RAM**. TM1637 / segment / HD44780
fit in IRAM. Colour or OLED graphics need SRAM and `--xram-size`.

The 8051 port's own demos compile the same way:

```bash
python -m niusburner compile <NiusDisplay>/ports/8051-sdcc/demo_tm1637.c \
  --board at89s52
```

## Commands

| Command | Does |
|---|---|
| `setup` | what to install so `upload` can run here |
| `boards` | parts, flash size, programmer, status |
| `compile` | build an image; do not touch the chip |
| `upload` | compile, probe, erase, program, verify |
| `detect` / `list` / `which` | toolchain and programmer inventory |
| `probe` / `flash` / `build-mcs51` | low-level; still require `--confirm` |

`flash` stays explicit (`--ack-data-loss --state-policy replace`) because it
is the dangerous verb. `upload --yes` is the same acknowledgement with the
board already known.

Wiring: [families/8051.md](families/8051.md), [wiring/usbasp-idc10.md](wiring/usbasp-idc10.md).
