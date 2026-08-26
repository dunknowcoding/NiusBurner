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
   programming only, no debugging.
2. **MPLAB X 5.35**, which keeps both programming and debugging.
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

### Debugging

The PIC16F877A supports in-circuit debugging over ICSP with MPLAB X 5.35 and a
PICkit 3 — **real breakpoints and single-stepping**, which none of the 8051
parts can offer. If a display driver misbehaves on hardware, this is by far the
best part in the collection to reproduce it on.

Debugging consumes some RAM and a few program words, and RB6/RB7 become
unavailable while a debug session is live.

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
