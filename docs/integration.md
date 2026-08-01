# Using NiusBurner from another project

NiusBurner has **no dependency on any of its consumers**. It is a standalone
tool for building and flashing parts the Arduino IDE cannot reach, and it works
against any source tree.

That direction matters and is deliberate: consumers depend on NiusBurner, never
the reverse. A tool that knew about the projects using it could not be shipped
to anyone else, and could not be reasoned about on its own.

```
    NiusDisplay  ─┐
    the simulator     ─┼──>  NiusBurner  ──>  C:\embd_toolchains
    (future libs)─┘
```

## NiusDisplay

NiusDisplay is a **plain Arduino library** and must stay one. The Arduino IDE
compiles everything under `src/`, so anything that is not portable C/C++ for the
target belongs outside it — and in practice, outside the repository.

That is why the AT89C2051 programmer, the 12 V wiring, the Intel HEX handling
and the per-family programming guides live here rather than there. A user who
installs NiusDisplay through the Library Manager gets a display library; a user
who wants to flash an 8051 gets NiusBurner as well.

The split is by *what the file is*, not by what it is about:

| Stays in NiusDisplay | Moves to NiusBurner |
|---|---|
| `src/**` — the library the IDE compiles | programmer firmware and host flashers |
| its own `tests/`, `examples/` | per-family programming and wiring guides |
| `ports/**` — HAL implementations, source only | toolchain discovery and install |
| `tools/compile_matrix.py` — verifies *this library* | flashing, chip erase, signature checks |

## the simulator

the simulator needs real firmware to be worth trusting. Simulating a hand-written
image proves something about the simulator; simulating **the image that would
actually be flashed** proves something about the firmware.

So the flow is: source → NiusBurner builds it with the real toolchain → the
resulting `.ihx`/`.elf` is what the simulator executes. Nothing in the chain is
a special "simulation build", because a special build is exactly where the
divergence would hide.

This is also why NiusBurner carries **ARM and RISC-V** toolchains even though
the Arduino IDE supports those targets perfectly well. A simulator needs a
compiler it controls and can pin a version of, not whatever a board package
happens to bundle this month.

## The contract

Two things, both stable:

**A CLI.** `list`, `detect`, `which <part>`, `flash <part>`. Machine-readable
output is added when a consumer needs it, not before.

**A Python API.**

```python
from niusburner import registry

registry.scan()                     # everything, with why it is missing
registry.for_family("mcs51")        # compilers that build for a family
registry.programmers_for("at89s52") # every route to a part, not one
```

`programmers_for` returns **all** options rather than a recommendation. An
STC89C52RC can be written over SPI ISP with a USB-ISP or through its serial
bootloader, and which is right depends on how the board is wired — a choice
that belongs to whoever can see the bench.

## What NiusBurner will not do

- **Guess.** If a toolchain is missing it says which and where to get it. It
  never silently substitutes another compiler, because a build that succeeded
  with the wrong one is worse than a build that failed.
- **Vendor.** See [toolchains.md](toolchains.md).
- **Flash without a check.** `detect` is separate from `flash` so that an
  environment problem surfaces before a chip is half-erased.
