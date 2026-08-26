# Programmer hardware

This tree is **not target firmware**. The `.ino` files here run on a **host
Arduino we use as a programmer**, then that board programs a chip that has no
USB-ISP of its own.

AT89S52 blink / NiusDisplay clocks belong in [`examples/`](../examples/). Those
are compiled by SDCC and burned with `python -m niusburner upload`. Do not put
them here, and do not `upload` a file from `hardware/` onto an 8051.

## Why these are `.ino` at all

The Nano *is* a normal Arduino. Its firmware is written and flashed the Arduino
way (`arduino-cli` / the IDE) onto the Nano's ATmega328P. NiusBurner does not
compile these files: SDCC does not build AVR, and this sketch is not for the
AT89C2051 in the ZIF socket.

```
  hardware/*.ino  --arduino-cli-->  Nano (programmer)
                                      |
                                      | 12 V parallel algorithm
                                      v
                                   AT89C2051 (target, no ISP)
```

Contrast:

```
  examples/*.ino  --niusburner upload-->  AT89S52 (target, USB-ISP HID)
```

Same filename suffix, opposite direction. Mixing them is how a Nano programmer
sketch gets mistaken for an AT89S52 sketch.

| Directory | Runs on | Programs | Flashed with |
|---|---|---|---|
| [`nano_at89c2051/`](nano_at89c2051/) | Arduino Nano V3 | AT89C2051 | `arduino-cli` onto the **Nano** |

```bash
# Once: put the programmer firmware on the Nano.
arduino-cli compile -b arduino:avr:nano --upload -p <PORT> \
    hardware/nano_at89c2051/nano_at89c2051.ino

# Target sketches still go through NiusBurner, never this folder:
python -m niusburner upload examples/at89s52_blink --board at89s52 --yes
```

Physical programming of the AT89C2051 through this Nano is not wired to
`upload` yet. Building the Nano firmware is.
