# AT89C2051 programmer

A 12 V parallel programmer hosted on an Arduino Nano V3, for a chip that has
no ISP of any kind and cannot be reached by a USB-ISP.

| File | What it is |
|---|---|
| `nano_at89c2051.ino` | Nano firmware — 3,972 B, 12% of the board |
| `flash.py` | Host tool: Intel HEX parsing, erase, write, verify, read back |

**Full wiring, the 12 V rail, the safety rule and the procedure are in
[docs/hardware/programming-8051.md](../../docs/hardware/programming-8051.md).**
That guide also covers the AT89S52, STC89C52RC and STC15W408AS, which all use
different routes.

## Quick reference

```bash
arduino-cli compile -b arduino:avr:nano --upload -p <PORT> nano_at89c2051.ino

niusburner package at89c2051 firmware.ihx out
```

Physical use remains blocked until the external programming backend is
for this exact 12 V programmer protocol. NiusBurner does not carry a second
host flasher or bypass `niusprog` identity, backup, verification, and restoration
gates.

> ### ⚠️ A2 and A3 must never be high together
> A2 switches 12 V onto RST; A3 switches 5 V. Both high connects 12 V to the
> Nano's 5 V rail and destroys it. The firmware drives both low before raising
> either — build the hardware so it cannot happen either.

## Serial protocol

Line-based text, so it can be driven from a terminal by hand when something is
wrong. On a part with no debug interface that matters.

| Command | Effect |
|---|---|
| `S` | Read signature. `SIG 1E 21` then `OK AT89C2051` |
| `E` | Chip erase |
| `R<n>` | Read `n` bytes as hex |
| `W<n>` | Write `n` bytes; replies `RDY`, then expects hex pairs |

Writing is sequential and verified byte by byte, because the chip has **no
address bus** — the counter resets on RST low and advances one step per XTAL1
pulse, so seeking is impossible and a failure must be reported at its exact
address.
