# Programming the 8051 parts

Four chips, three different routes. None of this is hardware-verified — the
parts are on order.

| Part | Flash | Route | Tool |
|---|---|---|---|
| **AT89S52** | 8 KB | SPI ISP | USB-ISP + ProgISP |
| **STC89C52RC** | 8 KB | SPI ISP *or* serial | USB-ISP + ProgISP, or `stcgal` |
| **STC15W408AS** | 8 KB | serial bootloader **only** | `stcgal` + USB-TTL |
| **AT89C2051** | 2 KB | 12 V parallel | [Nano programmer](#at89c2051--nano-v3-programmer) |

> **Read [the footprint section](#footprint-what-fits-and-what-does-not)
> before planning a project.** Segment and character displays fit the 8 KB
> parts comfortably (4,677 B). The graphics path does not fit any of them yet.

---

## The USB-ISP programmer

The IDC10 header is the standard AVR ISP pinout, printed on the case:

```
MOSI  1  2  VCC
NC    3  4  GND
RST   5  6  GND
SCK   7  8  GND
MISO  9  10 GND
```

### AT89S52 and STC89C52RC wiring

Both are DIP40 and share the same ISP pins, so one wiring serves both.

| IDC10 | Signal | DIP40 pin | Chip signal |
|---|---|---|---|
| 1 | MOSI | 6 | P1.5 |
| 9 | MISO | 7 | P1.6 |
| 7 | SCK | 8 | P1.7 |
| 5 | RST | 9 | RST |
| 2 | VCC | 40 | VCC |
| 4, 6, 8, 10 | GND | 20 | GND |

**A crystal is mandatory on the AT89S52.** 11.0592 MHz across XTAL1/XTAL2
(pins 19/18) with two 22 pF capacitors to ground. Without a running clock the
part does not answer the programmer, and the failure is indistinguishable from
bad wiring.

The STC89C52RC has an internal oscillator option but the RC variants are
usually run from a crystal too; fit one if the part does not respond.

### Software

**`avrdude` does not speak the 8051 ISP protocol** — the command bytes differ
from AVR's. Use **ProgISP**, the Windows tool normally supplied with these
programmers; it drives the same USB-ISP hardware and knows the AT89S5x and
STC89C5x algorithms.

Select the exact part in ProgISP's device list, then: *Erase → Program →
Verify*. Reading the signature first is worth the second it takes.

### If ProgISP will not take the STC89C52RC

Fall back to the serial bootloader, which every STC part has:

```bash
pip install stcgal
stcgal -P stc89 -p <PORT> firmware.hex
```

---

## STC15W408AS — serial only

This part has **no SPI ISP**. The USB-ISP cannot reach it.

| USB-TTL | STC15W408AS |
|---|---|
| TXD | P3.0 / RXD |
| RXD | P3.1 / TXD |
| GND | GND |
| 5 V or 3.3 V | VCC |

```bash
stcgal -P stc15 -p <PORT> firmware.hex
```

`stcgal` prints `waiting for MCU` and then **you must power-cycle the board** —
the bootloader only listens in the first few milliseconds after reset. Pulling
VCC and reconnecting it is the whole procedure.

No crystal needed; the part has an internal oscillator.

---

## AT89C2051 — Nano V3 programmer

This chip has **no ISP of any kind**. It is not in the USB-ISP's supported
list, and that is not an omission: the silicon has no serial programming
interface. It is programmed by a 12 V parallel algorithm.

Everything needed is in [`tools/at89c2051_prog/`](../../tools/at89c2051_prog/).

### What makes it awkward

**There is no address bus.** The internal address counter resets when RST goes
low and advances one step per pulse on XTAL1. Programming is strictly
sequential from address 0 — you cannot seek, and rewriting a single byte means
walking the counter back to it from zero.

### Wiring

| Nano | DIP20 pin | Signal |
|---|---|---|
| D2–D9 | 12–19 | P1.0–P1.7 (data bus) |
| D10 | 5 | XTAL1 — counter advance |
| D11 | 6 | P3.2 `/PROG` |
| D12 | 7 | P3.3 ┐ |
| D13 | 8 | P3.4 │ mode select |
| A0 | 9 | P3.5 │ |
| A1 | 11 | P3.7 ┘ |
| A2 | — | enable for the **12 V** switch onto RST (pin 1) |
| A3 | — | enable for the **5 V** path onto RST (pin 1) |
| 5V | 20 | VCC |
| GND | 10 | GND |

### The 12 V rail

**The Nano cannot generate 12 V.** RST/VPP needs it during write and erase.
Use a boost module or a bench supply, switched by a transistor driven from A2.
A3 drives a separate plain-5 V path for the modes that want V<sub>IH</sub>.

A workable switch is a PNP or P-channel device on the 12 V rail with an NPN
level-shifter from A2, and a diode-OR or second transistor for the 5 V path.
Whatever the arrangement:

> ### ⚠️ A2 and A3 must never be high together
>
> That connects 12 V to the Nano's 5 V rail and destroys it — and probably the
> USB port feeding it.
>
> `assertRst()` in the firmware drives **both** low and waits before raising
> either, so software cannot cause it. **Build the hardware so it cannot
> happen either** — if one transistor can be on while the other is, a stuck
> pin at power-up is enough.

### Procedure

```bash
# 1. Flash the programmer firmware onto the Nano (once)
arduino-cli compile -b arduino:avr:nano --upload -p <PORT> \
    tools/at89c2051_prog/nano_at89c2051.ino

# 2. Wire the target, apply the 12 V rail, then ALWAYS check the signature
niusburner package at89c2051 firmware.ihx out
#    expects: SIG 1E 21  /  OK AT89C2051

# 3. Flash
niusprog --config targets.local.json burn <TARGET> out/firmware.ihx \
  --confirm <TARGET> --ack-data-loss --state-policy replace

# 4. Read back if you want an independent check
niusprog --config targets.local.json dump <TARGET> 0 <SIZE> backup.bin
```

The signature step costs a second and separates "the 12 V rail is not
switching" from "my code is wrong". On a part with no debug interface that is
most of the diagnostic information available, so do not skip it.

Every byte is verified as it is written, and a failure reports the exact
address rather than surfacing later as a corrupt image.

---

## Debugging: what is actually possible

**None of these four parts has a debug interface.** No JTAG, no on-chip debug,
no breakpoints, no single-stepping. That is a property of the silicon; no
programmer adds it.

What genuinely works, most useful first:

1. **Host-side protocol tests** — check display initialization, addressing,
   offsets, and rendering against controller data sheets before programming a
   chip. Most display bugs never need to reach hardware at all.
2. **UART `printf`** — all four parts have a hardware UART on P3.0/P3.1. On the
   STC parts the adapter is already connected for flashing, so this is free.
3. **A GPIO toggled as a scope trigger** — crude, but on a part with 128 bytes
   of RAM it is sometimes the only thing that fits.

The AT89S52 and the STC parts have room for real logging. **The AT89C2051 does
not** — with 2 KB of flash a handful of `printf` calls is a measurable
fraction of the budget. Treat it as a deployment target, not a development
one: get the code right on a bigger part first.

---

## Footprint: what fits and what does not

### ✅ Segment and character displays fit

A TM1637 needs no graphics stack — `nd_tm1637.h` includes only `nd_hal.h`.

| Flags | CODE |
|---|---|
| `-DND_TINY=1` | 4,677 B |
| `+ -DND_HAL_BUSES=0` | **3,419 B** |

3,419 B is **42% of an 8 KB part**, leaving most of the flash for your
application. Build a segment project with:

```
-DND_TINY=1 -DND_HAL_BUSES=0
```

`ND_HAL_BUSES=0` removes SPI, I2C and parallel from the port HAL — nine of its
sixteen functions, which a two-wire TM1637 never touches. SDCC links them
anyway because it eliminates dead code per module, not per function.

Prefer `nd_tm1637_show_i16()` over `show_int()`: a 4-digit module cannot exceed
9999, and the 32-bit form costs about 1,600 bytes of SDCC runtime.

### The AT89C2051 (2 KB) still does not fit

3,419 B is 1.7x over. The remaining bulk is the TM1637 driver's own nine public
functions — init, brightness, display on/off, raw write, clear, integer, time,
and the segment table. A hand-written routine that does exactly one thing is
around 300 bytes, and that is the honest comparison: the gap is API surface,
not inefficiency.

Two notes for anyone trying to close it:

- `--model-small` does **not** help. It fails to link — *"could not get 54
  consecutive bytes in internal RAM"* — because the part has 128 bytes of IRAM
  and no XRAM at all. `--model-large` with `--stack-auto` is what links.
- Dropping to `init` + `show_i16` + `brightness` alone would get close to 2 KB,
  but at that point a purpose-written routine is the better engineering.

### ⚠️ The graphics path does not fit yet

Measured with SDCC, not estimated:

| Build | CODE | AT89C2051 (2 KB) | The 8 KB parts |
|---|---|---|---|
| Full | 38,003 B | ✗ | ✗ |
| `-DND_TINY=1` | 24,123 B | ✗ | ✗ |

`ND_TINY` drops shapes, text and bitmaps — a 36% saving that is still three
times too large. The cause is `nd_u32` buffer arithmetic pulling in
`__divslong`, `__divulong`, `__modulong` and `__mullong`; 32-bit division on
an 8-bit CPU is a called routine every time.

Fitting 8 KB needs a DIRECT-only build, 16-bit counts on 8-bit targets, and
compiling only the bus transport in use. Estimated 6–9 KB. **Not done yet** —
tracked as the top priority.
