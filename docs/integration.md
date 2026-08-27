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
library. Flashing an 8051 uses NiusBurner on the same machine. After
`python -m niusburner setup --board at89s52` the Arduino IDE also grows a
**NiusBurner 8051 (SDCC)** board: Verify/Upload drive SDCC and the USB-ISP.
NiusDisplay still has **no** `depends=NiusBurner`.

1. Keep editing the sketch in Arduino IDE (sketchbook folder).
2. Install NiusBurner + SDCC; `python -m niusburner setup --board at89s52`.
3. For AT89S52, pick the NiusBurner board (or stay on the CLI). BASIC C++
   (`NiusSegment`) is rewritten to C; `NiusTFT` / `String` still will not
   compile. `.S` files are sdas8051, not avr-as.
4. CLI alternative: `python -m niusburner upload <sketch-folder> --board at89s52 --yes`.

Other libraries lower the same way once they ship `<Lib>/niusburner/adapter.json`
(NiusIMU is that layout; only NiusDisplay is implemented today). NiusBurner
finds the Library Manager copy under the Arduino sketchbook
`libraries/NiusDisplay` folder. It does not import the Python package.

## The contract

**A CLI.** `setup`, `boards`, `lower`, `compile`, `upload` are the workflow.
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
- **Pretend SDCC compiles C++.** A BASIC NiusSegment / Serial sketch is
  rewritten to C first (`niusburner lower`). `NiusTFT` / `String` / `class`
  are still refused, with a rewrite path or the IAR core.
