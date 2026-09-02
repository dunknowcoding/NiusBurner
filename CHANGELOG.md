# Changelog

All notable changes to NiusBurner. Versions follow [semantic versioning](https://semver.org/).

## 0.6.0 — 2026-09-02

Correctness release. Several faults here had been present for a while and
were invisible because they only misbehaved on parts nobody had tried yet.

### Fixed

- **The 8051 family was decided from the part's name.** `"stc89"` starts with
  `"stc8"`, so a prefix test matched every STC89 — and every AT89, SST89, W78
  and STC90 part that shares its protocol string. Twenty-five boards were
  built as 1T parts and told they select UART1's clock in AUXR, which they do
  not. It stayed hidden because a plain AT89S52 has no register at that
  address, so the write landed nowhere. The family is now read from the
  catalog: `Board.is_one_t` from clocks per machine cycle, and
  `Board.uses_bootloader` from the programmer.
- **`probe` never worked on an STC part.** It shelled out to `stcgal` for all
  of them, while `flash` routes STC8 and STC15 to the native handler that
  exists *because* stcgal cannot hold their handshake — and it passed an
  option this build of stcgal does not have, so it exited on argument parsing
  before opening the port. It now takes the same route `flash` does.
- **`delay()` ran 12.5 % fast on the 1T cores.** The timing constants were
  measured on a 12-clock AT89S52 and inherited by parts that do not execute
  the same opcodes in the same number of cycles. Refitted on silicon:
  `delay(1000)` measures 1000.2 ms, from 875.1 ms.
- An argument error from the programming tool was reported as *"the
  bootloader did not answer"*, sending the reader to check wiring for a fault
  that never reached the wire.
- Two PICkit 3 power faults were both reported as *"the part must be powered
  — pass `--power`"*, which is wrong when `--power` was already given and the
  board is pulling the rail down.

### Added

- `compile --debug-symbols` asks SDCC for its debug database and keeps the
  listings beside the image. The link map names only globals, so without it
  anything declared `static` has no name and no address anywhere in the
  output.
- Boards can carry their own measured `spin_mc` and `delay_mc_q8` in the
  catalog, so a part that has been timed uses its own numbers instead of
  inheriting another core's.

### Changed

- The Arduino IDE documentation leads with Boards Manager, and its board
  counts match the catalog again: 62 parts, 52 of which flash from Upload.
