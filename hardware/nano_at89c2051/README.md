# AT89C2051 programmer (Arduino Nano)

Firmware that runs **on the Nano**, turning it into a 12 V parallel programmer
for a chip that has no ISP. This is not a sketch for the AT89C2051 itself.

| File | What it is |
|---|---|
| `nano_at89c2051.ino` | Nano firmware — 3,972 B, 12% of the board |

Host-side erase/write/verify is `niusprog` / `python -m niusburner flash`,
not a second Python flasher in this folder. Physical use of this 12 V
protocol is still pending a `niusprog` backend.

**Wiring, the 12 V rail, the safety rule and the procedure:**
[docs/families/8051.md](../../docs/families/8051.md).

```bash
arduino-cli compile -b arduino:avr:nano --upload -p <PORT> nano_at89c2051.ino
```

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
