<div align="center">

# NiusBurner

**One-key compile and upload for the microcontrollers the Arduino IDE forgot.**

Write a sketch that looks like Arduino. Press Upload. It lands on an 8051 or a PIC.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Parts](https://img.shields.io/badge/parts-58-green.svg)](#supported-parts)
[![Toolchains](https://img.shields.io/badge/toolchains-never%20vendored-orange.svg)](docs/toolchains.md)

</div>

---

## Why

The Arduino IDE speaks AVR, ARM and Xtensa. It does not speak 8051 or PIC —
those parts have no C++ compiler, no common bootloader, and a different
programmer for every family.

NiusBurner closes that gap. It keeps the part of Arduino that matters — write
`setup()` and `loop()`, press one button — and does the unglamorous work
underneath: translating C++ to C, driving SDCC or XC8, framing the programmer
protocol, and reporting what actually happened.

```cpp
void setup() {
  pinMode(13, OUTPUT);
  Serial.begin(9600);
}

void loop() {
  digitalWrite(13, HIGH);
  delay(200);
  digitalWrite(13, LOW);
  delay(200);
}
```

That sketch compiles and runs on an AT89S52, an STC89C52RC and a PIC16F877A,
unchanged.

## Quick start

NiusBurner is a **boards platform**, so it installs through Boards Manager.
Add this to **File → Preferences → Additional Boards Manager URLs**:

```
https://github.com/dunknowcoding/NiusBurner/releases/latest/download/package_niusrobotlab_index.json
```

then **Tools → Board → Boards Manager**, search `NiusBurner`, and install the
families you want. Restart the IDE and press **Upload**.

Each platform carries the tool inside it, so there is nothing to clone and
nothing to run. **Python 3.10+ is the only prerequisite** — and nothing is
installed *into* it: no `pip install`, no virtual environment.

Prefer the command line, or want to read the source?

```bash
git clone https://github.com/dunknowcoding/NiusBurner
cd NiusBurner
python -m niusburner setup        # installs the board packages, finds the tools
python -m niusburner upload examples/at89s52_blink --board at89s52 --yes
```

New to this? [**docs/getting-started.md**](docs/getting-started.md) covers the
hardware to buy, the drivers and compilers to install, and how to wire both
families — including the one MPLAB X version trap that costs PIC users an
afternoon.

On Windows, the one thing worth reading first is
[which Python to install](docs/getting-started.md#2-install-python-windows-first),
because the default `python` on a clean Windows is a Store placeholder that
does nothing.

## Supported parts

**Serial ISP** — written straight through the ISP header. Nothing to press.

| part | flash | RAM |
|---|---|---|
| AT89S2051 | 2 KB | 128 B |
| AT89S4051 | 4 KB | 128 B |
| AT89S51 | 4 KB | 128 B |
| AT89S52 | 8 KB | 256 B |
| AT89S53 | 12 KB | 256 B |
| AT89S8252 | 8 KB | 256 B |
| AT89S8253 | 12 KB | 256 B |

**UART bootloader** — written by `stcgal` through a USB-serial adapter.

| part | flash | RAM |
|---|---|---|
| STC89C51RC | 4 KB | 256 B |
| STC89C52RC | 8 KB | 256 B |
| STC89C53RC | 12 KB | 256 B |
| STC89C54RD | 16 KB | 256 B |
| STC89C58RD | 32 KB | 256 B |
| STC90C51RC | 4 KB | 256 B |
| STC90C52RC | 8 KB | 256 B |
| STC90C58RD | 32 KB | 256 B |

**PIC over ICSP** — written by a PICkit 3, compiled by XC8.

*PIC10/12/16 (14-bit core), flash in words:*

| part | flash | RAM | ports | USART |
|---|---|---|---|---|
| 12F629 ⚠️ | 1 K words | 64 B | GPIO | — |
| 12F675 ⚠️ | 1 K words | 64 B | GPIO | — |
| 12F683 ⚠️ | 2 K words | 128 B | GPIO | — |
| 16F627A ⚠️ | 1 K words | 224 B | A-B | yes |
| 16F628A ⚠️ | 2 K words | 224 B | A-B | yes |
| 16F648A ⚠️ | 4 K words | 256 B | A-B | yes |
| 16F84A ⚠️ | 1 K words | 68 B | A-B | — |
| 16F873 ⚠️ | 4 K words | 192 B | A-C | yes |
| 16F873A | 4 K words | 192 B | A-C | yes |
| 16F874 ⚠️ | 4 K words | 192 B | A-E | yes |
| 16F874A | 4 K words | 192 B | A-E | yes |
| 16F876 ⚠️ | 8 K words | 368 B | A-C | yes |
| 16F876A | 8 K words | 368 B | A-C | yes |
| 16F877 ⚠️ | 8 K words | 368 B | A-E | yes |
| 16F877A | 8 K words | 368 B | A-E | yes |
| 16F88 ⚠️ | 4 K words | 368 B | A-B | yes |

*PIC18 (16-bit core), flash in bytes:*

| part | flash | RAM | ports |
|---|---|---|---|
| 18F252 ⚠️ | 32 KB | 1536 B | A-C |
| 18F2520 ⚠️ | 32 KB | 1536 B | A-C |
| 18F2550 ⚠️ | 32 KB | 2048 B | A-C |
| 18F2620 ⚠️ | 64 KB | 3968 B | A-C |
| 18F452 ⚠️ | 32 KB | 1536 B | A-E |
| 18F4520 ⚠️ | 32 KB | 1536 B | A-E |
| 18F4550 ⚠️ | 32 KB | 2048 B | A-E |
| 18F4620 ⚠️ | 64 KB | 3968 B | A-E |

**dsPIC30F over ICSP** — 16-bit core, written by a PICkit 3, compiled by XC16.

| part | flash | RAM | ports | UART |
|---|---|---|---|---|
| dsPIC30F2010 ⚠️ | 7 KB | 512 B | BCDEF | yes |
| dsPIC30F2011 ⚠️ | 7 KB | 1024 B | BCD | yes |
| dsPIC30F2012 ⚠️ | 7 KB | 1024 B | BCDF | yes |
| dsPIC30F3012 ⚠️ | 15 KB | 2048 B | BCD | yes |
| dsPIC30F3013 ⚠️ | 15 KB | 2048 B | BCDF | yes |
| dsPIC30F3014 ⚠️ | 15 KB | 2048 B | ABCDF | yes |
| dsPIC30F4011 ⚠️ | 31 KB | 2048 B | BCDEF | yes |
| dsPIC30F4012 ⚠️ | 31 KB | 2048 B | BCDEF | yes |
| dsPIC30F4013 ⚠️ | 31 KB | 2048 B | ABCDF | yes |

Ports are named rather than counted here: several of these parts have no
PORTA at all, and one skips PORTE.

**Compile only** — these parts are written in a parallel programming socket,
which no header here can drive. They compile and size correctly, and `upload`
says plainly that the route is not wired: AT89C2051, AT89C51, AT89C52, AT89C55, SST89E54, SST89E564, W78E51, W78E52, W78E54, W78E58.

Parts marked **⚠️ experimental** (39 of them) are in the catalog on the
strength of their datasheet and their family: they compile and size
correctly, but something on the path — a programming mode, a pin map, where
a peripheral sits — is still an assumption. The Tools menu and
`niusburner boards` both say which.

`python -m niusburner boards` lists everything; `boards --features` says which
peripherals each part has.

## What you get

| | |
|---|---|
| **One button** | Compile, erase, program, verify and release, from the IDE or one command. |
| **Arduino API** | `pinMode`, `digitalWrite`, `Serial`, `delay`, `millis`, `shiftOut`, `random` — as C, on parts with no C++ compiler. |
| **C++ → C** | The translator lowers sketch C++ to C and passes inline assembly and register writes through untouched. |
| **Honest refusals** | Ask for `analogWrite` on a part with no PWM and it says so at compile time, naming the part and the feature. |
| **Real sizes** | Every build prints flash and RAM against the part's actual capacity, and fails closed on the limit rather than silently overflowing. |
| **No vendored toolchains** | Compilers are found, never shipped. |

## How it works

```
sketch.ino
   |  cxxlower      C++ -> C, assembly and registers untouched
   v
   C sources + the Arduino runtime for this family
   |  build / build_pic     SDCC (mcs51) or XC8 (pic16)
   v
   Intel HEX
   |  flash -> backends     USB-ISP HID | stcgal | PICkit 3
   v
   the part
```

Each stage is a separate module with its own tests, and the board catalog
([`niusburner/boards.json`](niusburner/boards.json)) is the single source of
truth for sizes, peripherals and transports — the IDE board menus are
generated from it rather than hand-maintained.

## Layout

```
examples/            target sketches (the MCU you are flashing)
hardware/            firmware for programmer appliances
  nano_at89c2051/    Nano as a 12 V parallel programmer - not a target sketch
docs/                workflow, IDE menus, translation limits, per-family notes
niusburner/
  __main__.py        CLI
  workflow.py        compile + upload
  cxxlower.py        Arduino C++ -> C
  boards.py          the part catalog
  build.py           SDCC driver          build_pic.py  XC8 driver
  flash.py           transport dispatch   backends/     USB-ISP, stcgal, PICkit 3
  adapters/Arduino/  the Arduino API as C, per family
  arduino/           generated Arduino IDE board packages
```

Two kinds of `.ino` live here and they are not interchangeable:

| Tree | Runs on | What it is |
|---|---|---|
| `examples/` | the target MCU | your sketch |
| `hardware/` | an Arduino Nano | programmer firmware, not a target sketch |

## What it is not

**It does not vendor toolchains.** `EMBD_TOOLCHAINS` names a directory on your
machine (default `~/.local/share/niusburner/toolchains`). Compilers are never
committed here; `setup` and `detect` say which tool is missing and where to get
it. See [docs/toolchains.md](docs/toolchains.md).

**It does not compile Arduino C++ on SDCC.** SDCC has no C++ mode. The
translator covers the sketch dialect — classes and templates are refused with
a reason, not miscompiled. See [docs/translation.md](docs/translation.md).

**It is not a substitute for the datasheet.** Timing is busy-wait and
interrupt-sensitive, the bit-banged buses run slow on purpose, and every one
of those trades is written down rather than hidden.

## Guides

| | |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | **start here** — what to buy, which drivers and compilers to install, how to wire it |
| [docs/workflow.md](docs/workflow.md) | setup, compile, upload |
| [docs/arduino-ide.md](docs/arduino-ide.md) | board and programmer menus, and what Upload prints |
| [docs/translation.md](docs/translation.md) | what the C++ to C translation covers, and what it refuses |
| [docs/assembly.md](docs/assembly.md) | writing assembly in a sketch, on either family |
| [docs/families/8051.md](docs/families/8051.md) | AT89S, AT89C, STC89/90, W78E, SST89 |
| [docs/families/pic.md](docs/families/pic.md) | the PIC16F87x family |
| [docs/wiring/usbasp-idc10.md](docs/wiring/usbasp-idc10.md) | ISP header pinout and wiring |
| [docs/toolchains.md](docs/toolchains.md) | why nothing is vendored |
| [docs/integration.md](docs/integration.md) | using NiusBurner from another project |

## Licence

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Third-party toolchains are **not** covered by that licence and are **not**
distributed here; each is fetched from its own vendor under its own terms.
