# Using the Arduino IDE

The Arduino IDE can drive NiusBurner directly: pick a board, press Upload,
watch the terminal. There is no GCC and no C++ compiler behind it — Verify
runs SDCC through NiusBurner, and Upload programs the chip over USB-ISP.

## Install

The IDE installs this the way it installs any boards platform. Put this in
**File → Preferences → Additional Boards Manager URLs**:

```
https://github.com/dunknowcoding/NiusBurner/releases/latest/download/package_niusrobotlab_index.json
```

then **Tools → Board → Boards Manager**, search `NiusBurner`, and install the
families you want. That URL always points at the newest release, so it is
pasted once and never again.

Each platform carries the tool inside it, so **Python 3.10+ is the only
prerequisite** and nothing is installed into it.

### From a checkout instead

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
| **Board → NiusBurner 8051 (SDCC)** | 29 parts: AT89S, AT89C, STC8, STC15, STC89/90, W78E, SST89 | AT89S52 |
| **Board → NiusBurner PIC16 (XC8)** | 16 parts: PIC12F6xx, PIC16F84A/62xA/88/87x | PIC16F877A |
| **Board → NiusBurner PIC18 (XC8)** | 8 parts: 18F2550/4550, 18F2520/4520, 18F2620/4620, 18F252/452 | PIC18F4550 |
| **Board → NiusBurner PIC24 (XC16)** | 9 parts: dsPIC30F2010/3013/4011/4013 and kin | dsPIC30F4013 |
| **Programmer** | USB-ISP HID (03EB:C8B4), USBasp, Nano 12 V | USB-ISP HID |
| **Clock** | As the board says, 4 / 8 / 11.0592 / 12 / 16 / 20 / 22.1184 / 24 MHz | **As the board says** |
| **Optimize** | Size, Speed, None | **Size** |
| **Compiler** | Auto-detect SDCC, configured path | Auto-detect |

The defaults are the safe answers, not the fastest ones:

- **Size**, because these parts run out of flash long before they run out of
  cycles. An empty sketch is 734 bytes of an 8 KB part; the margin is what
  you are spending.
- **Auto-detect**, because SDCC is normally on PATH or in its installer's
  directory. Switch to the configured path only after recording one.
- **As the board says**, because the catalog already records the crystal each
  part is usually sold with. Change it only when the board in front of you is
  fitted with a different one -- see below.

### When the board has a different crystal

The catalog's clock is what a part is normally sold with. It is not a fact
about the board on your desk, and a legacy board is often fitted with
whatever its designer had: 11.0592 MHz for exact serial rates, 12 MHz for
round instruction timing, 22.1184 for both at speed.

Getting it wrong is not subtle, and it does not announce itself. Every
derived number moves with it:

| what depends on the clock | what a wrong value does |
|---|---|
| UART baud divisor | the port talks at the wrong rate -- a PIC16F877A built for 20 MHz but fitted with 11.0592 transmits at 5308 baud, not 9600 |
| `delay()`, `delayMicroseconds()`, `millis()` | every interval is off by the same ratio -- 1.8x here |
| **PIC only:** the oscillator mode in the config word | above 4 MHz selects HS, below it XT. Choose the wrong one and the oscillator may not start at all |

So set **Tools → Clock** to the crystal actually fitted. From the command
line it is `--f-cpu`:

```bash
python -m niusburner upload sketch --board pic16f877a --f-cpu 11059200 --yes
```

The menu is offered on every part whose clock comes from outside. It is
withheld from the three PIC12F parts that run from an internal RC and have
no crystal to change.

**52 of the 62 parts flash from the Upload button**, over whichever transport
the part actually has: the USB-ISP header for AT89S, the part's own UART
bootloader for STC, and a PICkit 3 for every PIC.

The other ten compile but cannot be programmed from here, and say so before
anything is erased: nine need a 12 V parallel programming socket, and the
AT89C2051 needs its own carrier board. Choosing a programmer that does not
match the board is reported the same way -- before the erase, not after.

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

The console is the one ArduinoNRF's uploader established, so if you have
flashed an nRF52 with these tools it reads the same: the banner once, the
signature bar for each phase, then the closing summary.

Verify reports what the sketch cost against what the part has:

```
  NIUS  ......................    0%  Compiling  target at89s52
  NIUS  ======================  100%  Compiled  flash 1429/8192 B (17.4%)  iram 41/256 B
Sketch uses 1429 bytes of program storage space.
```

Upload prints the banner, then a bar with an ETA for every phase, because
programming an 8051 is one byte at a time at about 5 ms a byte — a 1.4 KB
image takes half a minute, and half a minute of silence is
indistinguishable from a hang:

```
*******************************************************************
    _   ___            ____        __          __  __          __
   / | / (_)_  _______/ __ \____  / /_  ____  / /_/ /   ____ _/ /_
  /  |/ / / / / / ___/ /_/ / __ \/ __ \/ __ \/ __/ /   / __ `/ __ \
 / /|  / / /_/ (__  ) _, _/ /_/ / /_/ / /_/ / /_/ /___/ /_/ / /_/ /
/_/ |_/_/\__,_/____/_/ |_|\____/_.___/\____/\__/_____/\__,_/_.___/
*******************************************************************
   8051 Flash Console - Target: at89s52

  NIUS  >.....................    5%  Connected  signature 1E 52 06
  NIUS  ======================  100%  Erasing  2.1s
  NIUS  ==============>.......   70%  Programming  856/1222 B  ETA 00:09
  NIUS  ======================  100%  Programming  1222 B in 30.9s
  NIUS  ======================  100%  Verifying  1245 B in 15.9s
  NIUS  ======================  100%  Upload complete

  Total upload time : 49.3s
  Soft reset        : done - board running the new firmware
  Power             : VCC still supplied by the programmer
```

In a terminal the bar is rewritten in place. The IDE panel renders a
carriage return as a line break, so there each phase prints at ten-percent
milestones instead of one line per byte.

Three things this console does on purpose, all carried over from the nRF52
tool:

- **Everything goes to stdout.** arduino-cli and Arduino IDE 2 capture both
  streams into one Output panel, so anything written to stderr is rendered
  red and, in a plain terminal, printed twice. Progress is not an error.
- **Every line is flushed.** A pipe block-buffers, and unflushed lines
  surface after the upload they were meant to introduce.
- **Quiet by default.** Internal detail lines are prefixed `[nius]` and are
  hidden unless `NIUSBURNER_VERBOSE=1`.

A failure is a block, not a stack trace — the reason, what to try, and the
trace only when there is one:

```
----------------------------------------------------------------
[nius][fail] ISP enable failed
 reason: no 0x69 ACK from the target
 hints:
  - check the IDC10 pin-1 alignment against docs/wiring/usbasp-idc10.md
  - confirm the board is powered and its crystal is running
  - an STC part in the same socket uses the UART bootloader, not this header
----------------------------------------------------------------
```

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
