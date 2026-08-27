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
| [`at89s52_asm_blink`](at89s52_asm_blink/) | AT89S52 | SDCC `sdas8051` | `python -m niusburner upload examples/at89s52_asm_blink --board at89s52 --yes` |
| [`at89s52_serial`](at89s52_serial/) | AT89S52 | above, plus CH341 on COM31 | `python -m niusburner upload examples/at89s52_serial --board at89s52 --yes` |
| [`niusdisplay_tm1637`](niusdisplay_tm1637/) | AT89S52 | USB-ISP, NiusDisplay, CH341 COM31 | `python -m niusburner upload examples/niusdisplay_tm1637 --board at89s52 --yes --port COM31 --expect "NB TM1637"` |
| [`niusdisplay_hd44780`](niusdisplay_hd44780/) | AT89S52 | I2C backpack on P1.0/P1.1 | same, `--expect "NB HD44780"` |
| [`niusdisplay_max7219`](niusdisplay_max7219/) | AT89S52 | MAX7219 on P1.2/P1.3/P1.4 | same, `--expect "NB MAX7219"` |

SDCC has no C++ compiler. Blink is C that reads like a sketch. `at89s52_asm_blink`
mixes that C with sdas8051 `.S` (Arduino IDE shows a second tab; this is **not**
AVR GNU as). Serial and `NiusSegment` sketches are BASIC Arduino C++ rewritten
by `niusburner lower`. `NiusTFT`, `String` and `class` are still refused.

```bash
python -m niusburner setup --board at89s52
python -m niusburner compile examples/at89s52_blink --board at89s52
python -m niusburner upload  examples/at89s52_blink --board at89s52 --yes
```
