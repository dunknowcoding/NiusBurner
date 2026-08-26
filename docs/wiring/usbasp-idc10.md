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

This dongle can source target VCC on IDC10 pin 2. `niusprog` enables it
during connect (the same HID command ProgISP calls 「提供电源」). A minimum
board with no USB-UART chip does not need a second supply if that connect
sequence ran.

If you power the board yourself, still share GND with the programmer.

## Which chip is in the socket

USB-ISP SPI is the **AT89S51/S52** serial programming protocol
(`AC 53 00 00` → ACK `0x69` in SPI byte 3).

An **STC89C52RC** in the same DIP-40 footprint does **not** implement that
state machine.  It is programmed through its UART bootloader (`stcgal` /
STC-ISP software) after a power cycle.

## Crystal

A crystal is **mandatory on the AT89S52** (11.0592 MHz, two 22 pF caps to GND
on XTAL1/XTAL2) unless the programmer is driving XTAL1.  `niusprog` also
sends ProgISP's 「提供时钟」 connect bytes.  Most min boards already have a
crystal; leave it fitted.

## USB protocol (ProgISP 1.72, captured)

All 4-byte SPI is Feature Report 1, **8 bytes**, never a 136-byte all-zero
Feature Report 2 (that USB-resets this firmware).

| Byte | Meaning |
|------|---------|
| 0 | report id `0x01` |
| 1 | command: `0x0F` identify, `0x0D` connect, `0x0E` SPI, `0x0B` disconnect |
| 2–5 | SPI TX (for `0x0E`) or connect parameters |
| 6–7 | `00 04` on every SPI transfer |

GET Feature Report 1: first 4 bytes are SPI RX; the useful payload is byte 3.

```bash
python -m niusburner probe at89s52 --confirm at89s52
python -m niusburner flash at89s52 out/firmware.ihx \
  --confirm at89s52 --ack-data-loss --state-policy replace
```
