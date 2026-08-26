# Using NiusBurner from another project

NiusBurner has **no dependency on any of its consumers**. Consumers depend on
NiusBurner, never the reverse.

```text
    source project  -->  NiusBurner  -->  compiler on this machine
                              -->  USB-ISP / other programmer
```

## NiusDisplay

NiusDisplay is a **plain Arduino library** and must stay one. The Arduino IDE
compiles everything under `src/`, so programmers, 12 V rails and SDCC live
here.

| Stays in NiusDisplay | Lives in NiusBurner |
|---|---|
| `src/**` — the library the IDE compiles | CLI: `setup`, `compile`, `upload` |
| `examples/` — Arduino C++ sketches | `examples/` — C-shaped `.ino` for 8051 |
| `ports/**` — HAL implementations, source only | USB-ISP HID, Nano 12 V firmware |
| `tools/compile_matrix.py` — verifies *this library* | toolchain discovery, chip erase |

A user who installs NiusDisplay through the Library Manager gets a display
library. A user who wants to flash an 8051 also installs NiusBurner:

```bash
python -m niusburner setup --board at89s52
python -m niusburner upload examples/niusdisplay_tm1637 --board at89s52 --yes
```

The library is found via `--library`, `NIUSDISPLAY`, a sibling checkout, or
the Arduino libraries folder. NiusBurner does not import it.

Arduino C++ examples (`#include <NiusDisplay.h>`) stay in NiusDisplay and
build with arduino-cli on AVR/ESP. They cannot build with SDCC; the 8051
path is NiusDuino C (see `ports/8051-sdcc` and this repo's
`examples/niusdisplay_tm1637`).

## The contract

**A CLI.** `setup`, `boards`, `compile`, `upload` are the workflow.
`list` / `detect` / `which` / `package` / `probe` / `flash` remain for
inventory and for an already-built image.

**A Python API.**

```python
from niusburner import registry, boards, workflow

registry.scan()
registry.programmers_for("at89s52")
boards.get_board("at89s52")
workflow.plan_compile(path, "at89s52")
```

`programmers_for` returns **all** options rather than a recommendation.

## What NiusBurner will not do

- **Guess** a compiler. Missing tools are named, not substituted.
- **Vendor** toolchains. See [toolchains.md](toolchains.md).
- **Erase without an acknowledgement.** `upload` needs `--yes`; `flash` needs
  `--ack-data-loss` and `--confirm`.
- **Pretend SDCC compiles C++.** A C++ `.ino` is refused with a rewrite path.
