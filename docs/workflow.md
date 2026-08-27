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
                         ├── USB-ISP HID (VID 03EB / PID C8B4)
                         └── CH341 UART on P3.0/P3.1 (Serial Monitor, e.g. COM31)
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
| C + sdas8051 `.S`, or SDCC `__asm` / `__endasm` | `examples/at89s52_asm_blink` | yes — not AVR GNU as |
| C `.c` with `main()` | any freestanding file | yes |
| NiusDuino C (NiusDisplay C API) | `examples/niusdisplay_tm1637` | yes — HAL + named drivers only |
| BASIC Arduino C++ (`NiusSegment`, `F()`, `Serial.method`) | NiusDisplay `examples/tm1637_clock_basic` | yes — `lower` rewrites it to the C API |
| Full Arduino C++ (`NiusTFT`, `String`, `class`, `Print`) | most other NiusDisplay examples | **no** — SDCC has no C++ compiler |

SDCC has no C++ mode. `python -m niusburner lower` is a subset rewriter,
not a C++ compiler: it maps the thin NiusDisplay BASIC facade onto the C
core. Colour/OLED sketches still need XRAM; they are refused on a minimum
AT89S52, not silently half-compiled.

Inspect the C without building:

```bash
python -m niusburner lower path/to/tm1637_clock_basic.ino -o sketch.c
```

`compile` and `upload` run the same rewrite automatically.

## Serial (CH341)

The USB-ISP dongle is HID and is not a COM port. UART logging uses a
**separate** CH341 USB-TTL on the AT89S52 hardware UART:

| CH341 (5 V) | AT89S52 |
|---|---|
| TXD | P3.0 / RXD (DIP-40 pin 10) |
| RXD | P3.1 / TXD (DIP-40 pin 11) |
| GND | GND |
| 5 V | VCC if the board is powered from the adapter |

Crystal **11.0592 MHz**. `Serial.begin(9600)` and `115200` are exact with
Timer 2. This bench uses **COM31**. Do not open COM35.

```bash
python -m niusburner upload examples/at89s52_serial --board at89s52 --yes
python -m niusburner monitor --port COM31 --baud 9600
```

Give `upload` a `--port` and it does both, in the order that actually works:
program, hold the part in reset, open the serial port, *then* release reset.
Resetting first loses whatever the sketch prints in its first milliseconds,
because Windows is still opening the COM port.

```bash
python -m niusburner upload examples/at89s52_serial --board at89s52 --yes     --port COM31 --seconds 8 --expect "AT89S52 serial"
```

If that verifies cleanly and prints nothing, check EA (DIP-40 pin 31) is
tied to VCC — see [wiring/usbasp-idc10.md](wiring/usbasp-idc10.md).

`Serial.print(float)`, `String`, and `HardwareSerial` extras are refused.
See the README table.

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
| `lower` | rewrite BASIC Arduino C++ to C; do not compile |
| `compile` | build an image; do not touch the chip |
| `upload` | compile, probe, erase, program, verify |
| `monitor` | read the CH341 UART (`--port COM31`); not the ISP dongle |
| `upload` | compile, probe, erase, program, verify |
| `detect` / `list` / `which` | toolchain and programmer inventory |
| `probe` / `flash` / `build-mcs51` | low-level; still require `--confirm` |

`flash` stays explicit (`--ack-data-loss --state-policy replace`) because it
is the dangerous verb. `upload --yes` is the same acknowledgement with the
board already known.

Wiring: [families/8051.md](families/8051.md), [wiring/usbasp-idc10.md](wiring/usbasp-idc10.md).

## With the Arduino IDE

`python -m niusburner setup --board at89s52` copies a board package into the
sketchbook:

```text
<sketchbook>/hardware/niusrobotlab/mcs51/
```

Then in the IDE: **Tools → Board → NiusBurner 8051 (SDCC) → AT89S52**.

| Button | What it does |
|---|---|
| Verify | SDCC via NiusBurner (C, BASIC C++ `lower`, `.S` / `__asm`) |
| Upload | USB-ISP HID; **erases** the AT89S52 (the click is the acknowledgement) |

Assembly in a sketch tab must be **sdas8051 (ASXXXX)** syntax, the same as
`examples/at89s52_asm_blink`. AVR GNU as (`lds`, `avr/io.h`, `r16`) will not
assemble. Inline SDCC:

```c
void loop(void) {
  __asm
    cpl P1.0
  __endasm;
  delay(200);
}
```

NiusDisplay remains a Library Manager install. The 8051 board package does
not add `depends=NiusBurner` to that library. You can still compile from a
terminal without the IDE:

```bash
python -m niusburner upload "%USERPROFILE%\Documents\Arduino\at89s52_asm_blink" ^
  --board at89s52 --yes
```

On POSIX the sketchbook is typically `~/Arduino` or `~/Documents/Arduino`.

The sketch itself may be C that reads like Arduino (`setup` / `loop`,
`NiusDuino.h`, `nd_tm1637.h`), BASIC C++ (`NiusSegment`, `F()`,
`Serial.method` — rewritten by `lower`), or sdas8051 `.S`. A sketch written
for Uno with `NiusTFT`, `String`, `Print` and `class` **Verify**s on AVR/ESP
and is **refused** for AT89S52. Colour/OLED also need XRAM this DIP-40 board
does not have.

Do not pick the Nano programmer sketch under `hardware/` as your target
firmware. That `.ino` is flashed onto the Nano with `arduino-cli`, not onto
an 8051.

