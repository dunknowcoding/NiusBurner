# Using the Arduino IDE

The Arduino IDE can drive NiusBurner directly: pick a board, press Upload,
watch the terminal. There is no GCC and no C++ compiler behind it — Verify
runs SDCC through NiusBurner, and Upload programs the chip over USB-ISP.

## Install

```bash
pip install hidapi pyserial
python -m niusburner setup
```

`setup` copies a small board package into your sketchbook at
`<sketchbook>/hardware/niusrobotlab/mcs51/` and records two things next to
it: which Python interpreter has NiusBurner, and where the package lives. The
IDE runs from the sketchbook with a working directory of its own, so both are
needed — you do not have to `pip install` NiusBurner for this to work.

Restart the IDE. `setup` prints what it found and what is missing; run it
again after installing anything.

## Tools menu

| Menu | Choices | Default |
|---|---|---|
| **Board → NiusBurner 8051 (SDCC)** | AT89S52, AT89S51, AT89C2051, STC89C52RC | AT89S52 |
| **Programmer** | USB-ISP HID (03EB:C8B4), USBasp, Nano 12 V | USB-ISP HID |
| **Optimize** | Size, Speed, None | **Size** |
| **Debug info** | None, Symbols and listings | None |
| **Compiler** | Auto-detect SDCC, configured path | Auto-detect |

The defaults are the safe answers, not the fastest ones:

- **Size**, because these parts run out of flash long before they run out of
  cycles. An empty sketch is 734 bytes of an 8 KB part; the margin is what
  you are spending.
- **Debug info: None**, because symbols cost build time and disk, not flash.
  Turning it on keeps the symbol database and per-unit listings next to the
  image, and changes nothing about the code that is programmed.
- **Auto-detect**, because SDCC is normally on PATH or in its installer's
  directory. Switch to the configured path only after recording one.

Only AT89S52 and AT89S51 can be flashed from the Upload button today. The
other two compile; AT89C2051 has no ISP at all (it needs the 12 V parallel
programmer) and the STC part is written through its UART bootloader, not this
header. Selecting a programmer that does not match the board is reported
before anything is erased.

## Compiler path

If SDCC is somewhere auto-detection does not look:

```bash
python -m niusburner setup --sdcc "D:/tools/sdcc/bin/sdcc.exe"
```

That records it in `~/.niusburner/config.json` (or `NIUSBURNER_CONFIG`).
Then set **Tools → Compiler → Use the path from `niusburner setup --sdcc`**.
`EMBD_TOOLCHAINS`, if set, is also searched. The search order is: recorded
path, PATH, the usual install directories, `SDCC_HOME`, then the toolchain
root.

## What Upload prints

Verify reports what the sketch cost against what the part has:

```
NiusBurner: compiling for at89s52
  3 translation unit(s), optimize=size
  flash 1429/8192 B  (17.4%)   iram 41/256 B
Sketch uses 1429 bytes of program storage space.
```

Upload shows each phase, with a bar and an ETA, because programming an 8051
is one byte at a time at about 5 ms a byte — a 1.4 KB image takes half a
minute, and silence for half a minute is indistinguishable from a hang:

```
Programming at89s52 over USB-ISP (VID 03EB / PID C8B4)
  signature 1E 52 06
  erase      done  2.1s
  write      [##########..................]  35.0%    487/1390 B  ETA 00:23
  write      [############################] done  1390 B in 34.4s
  verify     [############################] done  1390 B in 18.0s
  reset released - user code running, VCC still supplied
```

In a terminal this is one line rewritten in place. The IDE console renders
`\r` as a line break, so there it becomes twenty progress lines per phase
instead of one per byte.

Errors are named, not numbered. A refusal says which peripheral is missing,
which register to use instead, or which menu entry disagrees with the board.

## What the IDE cannot do here

- **No C++.** SDCC has no C++ mode. NiusBurner rewrites the Arduino shape of
  a sketch into C; `class`, `String`, templates and the rest are refused with
  a reason. See [translation.md](translation.md).
- **No AVR assembly.** `.S` tabs and SDCC `__asm` blocks are assembled with
  `sdas8051` (ASXXXX syntax), not `avr-as`.
- **No Serial Monitor for upload.** The USB-ISP dongle is an HID device, not
  a COM port. Use the IDE's Serial Monitor on your CH341 adapter, or
  `python -m niusburner monitor --port COM31 --baud 9600`.
- **Libraries** are translated only when they carry
  `<Library>/niusburner/adapter.json`. NiusDisplay ships one.

## Without the IDE

Everything the IDE does is one command:

```bash
python -m niusburner upload <sketch> --board at89s52 --yes --port COM31
```

That compiles, programs, holds the part in reset, opens the serial port, and
only then releases reset — so the sketch's first line of output is not lost
while the port is still opening.
