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

### PIC10/12/16 — XC8, 14-bit core

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

### PIC18 — XC8, 16-bit core

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

PIC18 program memory is counted in **bytes**; a mid-range PIC16 instruction
is one 14-bit **word**. Both are shown in the unit the compiler reports, so
the numbers can be compared with a datasheet without halving or doubling
anything.

**⚠️ experimental** means the entry comes from the datasheet and the family,
with something on the path still an assumption. It compiles and sizes
correctly.

### One runtime, compiled for the part in front of it

The family does not share one register map, and naming a register a part
does not have is a compile error rather than a pin that quietly does
nothing. So the catalog carries the differences and the runtime is built for
the part:

| What varies | Values seen across the family |
|---|---|
| Ports bonded out | A–E on 40-pin, A–B on 18-pin, and the 8-pin parts call their single port `GPIO`/`TRISIO` rather than `PORTA`/`TRISA` |
| Port pull-ups | `OPTION_REG.nRBPU` on the PORTB parts, `nGPPU` on the 8-pin ones, `INTCON2.RBPU` on PIC18 |
| Turning the analog pins off | `ADCON1`, `CMCON`, `ANSEL`, both together, or nothing to do |
| Where the USART sits | RC6/RC7, RB2/RB1, or RB2/RB5 |
| Configuration bits | The 16F84A implements neither brown-out nor low-voltage programming; the 16F62xA have no flash write protection |
| Oscillator setting | `HS`/`XT`/`LP` for a crystal, and `INTRCIO` or `INTOSCIO` for the same internal oscillator depending on the part |
| PIC18 configuration | The 18F4550 line spells them `FOSC`/`BOR`, the 18F4520 line `OSC`/`BOREN`, and the 18F452 line has neither `PBADEN` nor `MCLRE` |

A part with no USART refuses `Serial` at translation time, naming the part
and the peripheral, instead of failing later in the compiler.

### PIC24, dsPIC33 and PIC32

**Not supported yet.** `niusburner detect` finds XC16 and XC32 if they are
installed, because knowing a compiler is present is useful, but no board in
the catalog uses them.

What is missing is a runtime, not a compiler: those cores have a different
port model, a different UART, no `__delay_ms`, and — on most PIC24FJ parts —
peripheral pin select, so the UART has to be routed to pins before it
exists. Adding them means a new runtime and a new build driver per family,
which is a larger piece of work than widening an existing one.

---

## dsPIC30F — the 16-bit parts

Same programmer, different compiler: XC16 rather than XC8, and an ELF that
goes through `xc16-bin2hex` to become the HEX a PICkit 3 wants. Program
memory is counted in bytes.

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

Three things differ from the 8-bit parts enough to matter.

**Ports are named, not counted.** A dsPIC30F4013 brings out A, B, C, D and
F — no E — and several of these parts have no PORTA at all. The catalog
carries the set, and the runtime compiles in only the ports the package
actually bonds out.

**Writes go to the latch.** `LATx` exists so that a read-modify-write on one
pin cannot disturb its neighbours, which is the classic PIC hazard; `PORTx`
is only read.

**The configuration bits are spelled two ways.** Most of the family folds
the oscillator into `FOSFPR`; the 30F2010, 30F4011 and 30F4012 split it into
`FOS` and `FPR`. Same decision, different name, and naming the wrong one is
a compile error — so the catalog picks the spelling. Both come from the
compiler's own configuration tables rather than from a datasheet reading.

### What is deliberately not here

**PIC24F, PIC24H, PIC24E and dsPIC33.** They route the UART through
Peripheral Pin Select, which makes the physical pin a property of the board
rather than of the part. A runtime cannot guess it, and a `Serial` that
silently goes nowhere is worse than no `Serial`. dsPIC30F has fixed pins,
which is why it is the family that is here.

**PIC32.** It has a C++ compiler — `xc32-g++` ships in the same toolchain —
and an established Arduino core in chipKIT. This tool exists for parts that
have neither. Adding PIC32 would duplicate work that is already done better
elsewhere.

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
