# Programmer hardware

Sketches in this tree run on **programmer appliances we build**, never on the
target MCU.

| Directory | Runs on | Programs |
|---|---|---|
| [`nano_at89c2051/`](nano_at89c2051/) | Arduino Nano V3 | AT89C2051 (12 V parallel, no ISP) |

Target firmware — blink, NiusDisplay clocks, anything you `#include` and
`upload` — lives in [`examples/`](../examples/). Mixing the two is how a
Nano programmer sketch gets mistaken for an AT89S52 sketch.

```bash
# Flash the Nano (once). This is arduino-cli talking to the Nano, not NiusBurner.
arduino-cli compile -b arduino:avr:nano --upload -p <PORT> \
    hardware/nano_at89c2051/nano_at89c2051.ino

# Target sketches still go through NiusBurner:
python -m niusburner upload examples/at89s52_blink --board at89s52 --yes
```
