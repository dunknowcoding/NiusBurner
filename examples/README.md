# Target sketches

These directories are firmware for the **MCU you are programming** — the same
shape as an Arduino sketch: a folder named after the program, with a matching
`.ino`.

They are not programmer firmware. `hardware/*.ino` runs on an **Arduino Nano
used as a 12 V programmer**, flashed with `arduino-cli`, never with
`niusburner upload`. See [`hardware/`](../hardware/).

| Sketch | Board | Needs | Command |
|---|---|---|---|
| [`at89s52_blink`](at89s52_blink/) | AT89S52 | SDCC, USB-ISP HID | `python -m niusburner upload examples/at89s52_blink --board at89s52 --yes` |
| [`niusdisplay_tm1637`](niusdisplay_tm1637/) | AT89S52 | above, plus a NiusDisplay checkout | `python -m niusburner upload examples/niusdisplay_tm1637 --board at89s52 --yes` |

SDCC has no C++ compiler. These `.ino` files are C that reads like a sketch
(`setup` / `loop`). An Arduino C++ sketch that `#include <NiusDisplay.h>`
will be refused with a pointer to the C API, not fed to a compiler that
cannot parse it.

```bash
python -m niusburner setup --board at89s52
python -m niusburner compile examples/at89s52_blink --board at89s52
python -m niusburner upload  examples/at89s52_blink --board at89s52 --yes
```
