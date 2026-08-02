# NiusBurner

Build and package firmware for the parts the Arduino IDE cannot reach.

The Arduino toolchain stops at chips with a C++ compiler and a board package.
NiusBurner covers image resolution, building, and packaging for 8051, PIC,
MSP430, DSP, FPGA, ARM, and RISC-V toolchains.

It exists so that **NiusDisplay stays a plain Arduino library**. Everything
that is not `.h`/`.cpp` under `src/` — programmers, 12 V rails, Intel HEX,
`stcgal`, ISP wiring — lives here instead. Arduino IDE compatibility is not a
side effect of that split; it is the reason for it.

## What it is not

**It does not vendor toolchains.** Not one compiler, assembler or programmer
binary is committed to this repository. Third-party tools have their own
licences, their own update cadence and their own installers, and a copy pinned
inside a git repo goes stale silently and redistributes software we have no
right to redistribute.

Instead NiusBurner **locates** a toolchain below the caller-selected
`EMBD_TOOLCHAINS` root (or a per-user default) and records the exact version it
found. If a tool is missing, it says which one
and how to get it — it never silently substitutes another.

## Layout

```
niusburner/          the Python package and CLI
  registry.py        toolchain + programmer discovery
  toolchains.json    where each tool comes from, and how to detect it
programmers/         firmware for the DIY programmers we build ourselves
  nano_at89c2051/    Arduino Nano as a 12 V parallel programmer
docs/                per-family programming guides and wiring
tests/               host tests; no hardware required
_work/               gitignored: plans, progress, scratch
```

## Who uses it

| Consumer | Uses NiusBurner for |
|---|---|
| **NiusDisplay** | building and packaging its 8051 / PIC / MSP430 images without putting any of that in the library |
| **firmware simulators** | turning source into a real firmware image, so what is simulated is what would be flashed |
| future Arduino libraries | the same, unchanged |

Nothing here depends on those projects. NiusBurner is usable on its own with any
source tree.

## Status

Honest labelling, the same vocabulary the sibling projects use:

- `verified` — the operation has actually run end to end here
- `implemented` — code exists and is tested against a host stub, not silicon
- `planned` — documented, not written

| Target | Method | Status |
|---|---|---|
| AT89C2051 | Nano-hosted 12 V programmer firmware | `implemented`; physical `niusprog` backend pending |
| AT89S52 / STC89C52RC | USB-ISP over SPI | `planned` |
| STC15W408AS | `stcgal` serial bootloader | `planned` |
| PIC12F675 / PIC16F877A | PICkit 3 | `planned` |
| MSP430 | MSP430-GCC + mspdebug | `planned` |
| ARM / RISC-V (portable) | resolved below the configured toolchain root | `planned` |

**No part has been programmed with this yet — no hardware has been connected.**
Everything above is code and documentation, and says so.

## Quick start

```bash
python -m niusburner list
python -m niusburner detect
python -m niusburner package TARGET firmware.bin out
python -m niusburner flash TARGET out/firmware.bin \
  --confirm TARGET --ack-data-loss --state-policy replace
```

`package` creates a reproducible host-neutral manifest. `flash` never opens a
USB or programmer transport itself: it delegates exact identity, mutation,
verification, recovery, and restoration to an external programming
backend.

## Guides

- [docs/programming-8051.md](docs/programming-8051.md) — AT89S52, AT89C2051, STC89C52RC, STC15W408AS
- [docs/programming-pic.md](docs/programming-pic.md) — PIC12F675, PIC16F877A via PICkit 3
- [docs/toolchains.md](docs/toolchains.md) — what gets installed where, and why nothing lands in a repo
- [programmers/nano_at89c2051/](programmers/nano_at89c2051/) — building the 12 V programmer

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Third-party toolchains are **not** covered by that licence and are **not**
distributed here; each is fetched from its own vendor under its own terms.
