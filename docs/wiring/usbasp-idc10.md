# USB-ISP IDC10 wiring — AT89S52 / STC89C52RC

## Programmer

Manufacturer **zhifengsoft**, USB VID `03EB` / PID `C8B4`.  
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

## Power

The ISP VCC pin (IDC10 pin 2) is **sense-only** on this programmer.  
The target board **must be independently powered** via USB or a power adapter
before connecting the ISP cable.  Without independent power the board is
unpowered and MISO will read 0 on every SPI cycle.

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

## USB protocol notes (reverse-engineered)

The programmer communicates over USB Control (EP0) HID class requests only —
no interrupt endpoints.  Report sizes, read from the device descriptor:

| Report | Data bytes | Role |
|--------|------------|------|
| 1 | 7 | load 4 SPI TX bytes / read 4 SPI RX bytes |
| 2 | 135 | execute (header + 128-byte page). SET STALLs; a following USB reset means MISO stayed 0 |
| 3 | 127 | page-read buffer |
| 4 | 15 | status / control |

From the host's perspective for a 4-byte SPI command:

| Step | USB transfer | Meaning |
|------|-------------|---------|
| 1 | `SET_REPORT Feature ID 1` (8 bytes) | Load 4 SPI TX bytes |
| 2 | `SET_REPORT Feature ID 2` (136 bytes) | Execute SPI |
| 3 | `GET_REPORT Feature ID 1` (8 bytes) | Read 4 SPI RX bytes — only if step 2 did not USB-reset the dongle |
