# Programming the PIC parts

| Part | Flash / RAM | Package | Verdict for NiusDisplay |
|---|---|---|---|
| **PIC16F877A** | 14 KB / 368 B | DIP40 | Plausible with `ND_TINY`; not yet measured with XC8 |
| **PIC12F675** | 1 KB / 64 B | DIP8 | **Out of scope** — see below |

---

## ⚠️ PICkit 3 and modern MPLAB X

**MPLAB X 6.x removed PICkit 3 support.** If MPLAB X does not list the
programmer, that is why, and no amount of driver reinstalling will fix it.

Three options:

1. **MPLAB IPE** from an older MPLAB X (5.35 is the usual choice) — production
   programming.
2. **MPLAB X 5.35**, the last release that drives a PICkit 3.
3. **Replace it with a PICkit 4 or 5**, which current MPLAB X supports.

Command-line programming with `ipecmd` from a 5.35 install:

```bash
ipecmd -TPPK3 -P16F877A -F firmware.hex -M -OL
#      ^tool  ^part      ^image    ^program ^release from reset
```

---

## The ICSP adapter board

The universal adapter (silkscreened `AC164110 ICSP-RJ11`) carries several DIP
sockets and routes each to the RJ11 ICSP connector. Its own silkscreen is the
authority for which socket a part goes in — the groupings are printed on the
board:

- `DIP28, 40` — one row, for the larger parts including the **PIC16F877A**
- `DIP8, 14, 18, 20` — for the small parts including the **PIC12F675**
- separate labelled positions for `PIC16F57` and `PIC16F59`, which have
  different pinouts and are not interchangeable with the general rows

> **`请注意10F系列的方向` — "note the orientation of the 10F series".**
> The PIC10F parts are inserted the opposite way round from everything else in
> the same socket. This is printed on the board because it is easy to get
> wrong and doing so applies programming voltage to the wrong pins.

If a part is not in the printed list, wire ICSP directly rather than guessing a
socket. Only five signals are needed:

| ICSP | PIC16F877A | PIC12F675 |
|---|---|---|
| MCLR/VPP | 1 | 4 (GP3/MCLR) |
| VDD | 11, 32 | 1 |
| VSS | 12, 31 | 8 |
| ICSPDAT / PGD | 40 (RB7) | 7 (GP0) |
| ICSPCLK / PGC | 39 (RB6) | 6 (GP1) |

The PIC16F877A has **two** VDD and **two** VSS pins. Connecting only one pair
gives a part that programs intermittently or not at all.

---

## PIC16F877A

14 KB of flash and 368 bytes of RAM. Realistic for a display in
`ND_RENDER_DIRECT` mode with `ND_TINY`, since DIRECT needs no framebuffer —
a 240×240 panel would otherwise want 115 KB.

```bash
xc8-cc -mcpu=16F877A -DND_TINY=1 ...
```

**Not yet measured.** The 8051 build came to 24 KB under `ND_TINY`, and if XC8
lands anywhere near that this part is also too small. The measurement is
tracked as an open task; do not assume it fits.

---

## Parts

| part | flash | RAM | ports | USART |
|---|---|---|---|---|
| 16F627A | 1 K words | 224 B | A-B | yes |
| 16F628A | 2 K words | 224 B | A-B | yes |
| 16F648A | 4 K words | 256 B | A-B | yes |
| 16F84A | 1 K words | 68 B | A-B | — |
| 16F873 | 4 K words | 192 B | A-C | yes |
| 16F873A | 4 K words | 192 B | A-C | yes |
| 16F874 | 4 K words | 192 B | A-E | yes |
| 16F874A | 4 K words | 192 B | A-E | yes |
| 16F876 | 8 K words | 368 B | A-C | yes |
| 16F876A | 8 K words | 368 B | A-C | yes |
| 16F877 | 8 K words | 368 B | A-E | yes |
| 16F877A | 8 K words | 368 B | A-E | yes |
| 16F88 | 4 K words | 368 B | A-B | yes |

One runtime, compiled for the part in front of it. The family does not share
one register map: the 40-pin members bring out ports A to E and the 18-pin
ones stop at B; the analog pins are turned off through ADCON1, CMCON or
ANSEL depending on the part; the USART appears on RC6/RC7 or on PORTB; and
the 16F84A implements neither brown-out nor low-voltage programming, so those
configuration bits must not be named at all.

All of that is in the catalog rather than in the code, because naming a
register a part does not have is a compile error, not a pin that quietly
does nothing. A part with no USART refuses `Serial` at translation time with
that reason, instead of failing later in the compiler.

---

## The configuration word

A mid-range PIC takes its oscillator, watchdog and programming mode from a
word at `0x2007`, latched at reset rather than set by anything the program
does. An image that does not carry one is programmed onto whatever the
erased part already holds — all ones — which is the watchdog **on**, the
oscillator in RC mode and low-voltage programming **enabled**. Nothing in
the runtime clears a watchdog, so such an image resets roughly every 18 ms
whatever clock is fitted, and RB3 is not an I/O pin.

Every build therefore emits one:

| Bit | Value | Why |
|-----|-------|-----|
| `FOSC` | `HS` above 4 MHz, else `XT`/`LP` | follows the clock the board declares; `XT` cannot start a 20 MHz crystal |
| `WDTE` | off | nothing here clears the watchdog; a sketch that wants one should ask |
| `PWRTE` | on | holds reset while the supply settles |
| `BOREN` | on | resets rather than running under-volted |
| `LVP` | off | gives RB3 back, and matches how this toolchain programs the part |
| `CP` / `CPD` / `WRT` | off | nothing here needs the part locked |

A sketch needing its own settings defines `NIUS_NO_CONFIG` and supplies a
complete set. Two config blocks in one program is an error, not a merge.

Read back what actually landed with `niusburner probe --board pic16f877a`;
the programmer reports the device ID it found, and a wrong board selection
fails with `Invalid Device ID` rather than quietly succeeding.

---

## PIC12F675 — out of scope, and why

**1 KB of flash and 64 bytes of RAM.** NiusDisplay cannot run on it in any
configuration, and that is not a limitation worth engineering around.

The arithmetic is simple: `nd_bus` and `nd_panel` alone are structs of tens of
bytes, before any framebuffer, driver state or stack. Sixty-four bytes is the
entire data memory. Even the smallest `ND_TINY` build is over 20 KB of code
against 1 KB of flash.

This is a chip for blinking an LED, reading a sensor, or bit-banging a single
device — which it does very well. It is not a display controller host.

If you want a display on something this small, the realistic option is a
device that does its own rendering — a TM1637 or MAX7219, driven by a
hand-written 200-byte routine, not by this library.
