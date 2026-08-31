# USB-ISP IDC10 wiring — AT89S52 / STC89C52RC

## Programmer

USB VID `03EB` / PID `C8B4`, HID class device.  
Windows driver: **HidUsb** (the default Windows HID class driver — do **not**
replace it with WinUSB via Zadig; if WinUSB was accidentally installed,
revert by selecting HidUsb in Zadig and clicking Replace Driver).

## IDC10 pinout

```
MOSI  1 ●  2  VCC
NC    3    4  GND
RST   5    6  GND
SCK   7    8  GND
MISO  9   10  GND
```

Pin 1 is marked with a triangle on the plug and a `▼` or `1` label on the board.
**Misaligning pin 1 is the most common wiring mistake** — double-check before
powering the board.

## Target wiring (DIP-40)

| IDC10 | Signal | DIP-40 | Chip |
|-------|--------|--------|------|
| 1 | MOSI | 6 | P1.5 |
| 9 | MISO | 7 | P1.6 |
| 7 | SCK  | 8 | P1.7 |
| 5 | RST  | 9 | RST  |
| 2 | VCC  | 40| VCC  |
| 4,6,8,10 | GND | 20 | GND |

**EA/VPP (DIP-40 pin 31) must be tied to VCC.** It is not on the ISP header
and nothing above will tell you it is wrong. With EA low the AT89S52 fetches
every instruction from *external* program memory, so ISP still enables, the
signature still reads `1E 52 06`, and a flashed image still verifies byte for
byte — and none of it ever executes. If `upload` reports a clean verify and
the UART stays silent, measure pin 31 before suspecting anything else.

## Power

The ISP VCC pin (IDC10 pin 2) **sources 5 V from USB** and will run a small
target board on its own. It is a real supply, not a sense line, and it is
stiff enough to hold a board up unaided.

It is **not switchable from software.** No frame this programmer accepts
gates that pin. The vendor's own notes offer 3.3 V/5 V target switching only
"where the hardware supports it"; this unit does not.

So the programmer can reset a target but cannot power-cycle one, which
decides the upload route for any part whose bootloader is entered on
power-on. See `docs/families/8051.md`.

If MISO reads 0 on every SPI cycle the target is not powered at all — check
pin 1 alignment first.

## Which chip is in the socket

USB-ISP SPI is the **AT89S51/S52** serial programming protocol
(`AC 53 00 00` → ACK `0x69`).

An **STC89C52RC** in the same DIP-40 footprint does **not** implement that
state machine.  It is programmed through its UART bootloader (`stcgal` /
STC-ISP software) after a power cycle.  A SET of Feature Report 2 while MISO
stays 0 makes this dongle USB-reset — that is the programmer giving up, not a
successful SPI cycle.

## Crystal

A crystal is **mandatory** on the AT89S52 (11.0592 MHz, two 22 pF caps to GND
on XTAL1/XTAL2).  Without a running clock the chip never responds to SPI.

The STC89C52RC has an internal RC oscillator option, but most development boards
fit an external crystal and that is the path the toolchain targets.  If your
board lacks a crystal, stcgal over serial is the fallback route.

## USB transfer sequence

The programmer communicates over USB Control (EP0) HID class requests only —
no interrupt endpoints.  Report sizes, read from the device descriptor:

| Report | Data bytes | Role |
|--------|------------|------|
| 1 | 7 | load 4 SPI TX bytes / read 4 SPI RX bytes |
| 2 | 135 | page buffer; not part of a 4-byte SPI cycle |
| 3 | 127 | page-read buffer |
| 4 | 15 | status / control |

Report 1 is a **command register**, and the GET is what executes it. A
`SET_REPORT` only loads the payload; `GET_REPORT` runs it and returns the
result. Two SETs in a row therefore execute once, with the second payload.

`SET 0E 40 hi lo data` with no GET leaves the byte at
`0xFF`, and `SET 0E AC 80 00 00` with no GET never erases, however long you
wait. Never SET report 2 with zeros — that USB-resets the programmer.

| Step | USB transfer | Meaning |
|------|-------------|---------|
| 1 | `SET_REPORT Feature ID 1` (8 bytes) | Load one command: `01 0E b0 b1 b2 b3 00 04` |
| 2 | `GET_REPORT Feature ID 1` (8 bytes) | Execute it; first 4 bytes are the SPI RX, payload in byte 3 |

The command byte in position 1 selects what runs:

| Byte | Frame | Meaning |
|------|-------|---------|
| `0F` | `01 0F 01 00 00 00 02 00` | identify / select part family |
| `0D` | `01 0D 00 01 20 A0 40 C0` | byte 1 is the RST level, byte 2 target VCC, then four clock bytes |
| `0E` | `01 0E b0 b1 b2 b3 00 04` | 4-byte SPI transfer |
| `0B` | `01 0B 01 00 00 00 00 00` | tri-state the header |

The AT89S52 resets on a HIGH level, so the whole programming session runs
with `0D 01 …` and the part held in reset; `0D 00 01 00 00 00 00` is the
falling edge that starts user code, and RST measures 0.00 V after it. `0B`
is not that edge — it tri-states the header and leaves RST on a pull-up.

Chip erase needs about **3 s** here, not the datasheet's 500 ms.
A short erase does not leave a few stray bytes behind: every byte keeps its
high nibble, and repeating the short erase never finishes. The backend grows
its wait until a sample of the array actually reads `0xFF`.
