# Changelog

All notable changes to NiusBurner. Versions follow [semantic versioning](https://semver.org/).

## 0.6.1 — 2026-09-05

Bench release. A PIC16 could be compiled, programmed and verified, and then
sat there saying nothing — and everything on the path reported success while
it did.

### Fixed

- **A PIC16's serial port never transmitted.** `nius_serial_begin` cleared
  the transmit pin's TRIS bit, on the reasoning that a transmit pin has to be
  an output. This peripheral wants the opposite: *"Bit SPEN (RCSTA<7>) and
  bits TRISC<7:6> have to be set in order to configure pins RC6/TX/CK and
  RC7/RX/DT as the USART"* (PIC16F87XA §10.0). Clearing the bit does not help
  the USART drive the pin, it hands the pin to the port, and out of reset
  that latch is 0 — so the line was held low, which is a permanent break on a
  line that must idle high. A sketch printing its own registers shows the
  trap: TXSTA, RCSTA, SPBRG and even TRISC read identically whether it works
  or not, because the peripheral clears that TRIS bit as it takes the pin.
  Only PORTC differs, `0x80` against `0xC0`. Nothing reported a fault along
  the way either: `nius_serial_write` waits on TRMT, "the shift register is
  empty", which is exactly what it reads when nothing is ever shifted, so
  every write returned at once and every `println` completed.
- **Brown-out reset could not be turned off.** `NIUS_PIC_CFG_BOREN` says
  whether a part *has* the bit; there was no way to say what it should be, so
  every image hard-coded `BOREN = ON`. That is right for a clean 5 V rail and
  wrong near the trip point, where the part is held in reset while ICSP —
  which works far below 4 V — finds the device, erases, programs and verifies
  every byte. `NIUS_PIC_CFG_BOREN_ON` now carries the value, still on by
  default.
- **Reading a PIC left it in reset.** Neither `probe` nor the readback passed
  `-OL`, so the programmer kept MCLR asserted after it exited. Checking on a
  running board stopped it, and every check after the first then agreed it
  was not running — the diagnostic manufacturing the state it reported.

### Added

- **The serial monitor names a crystal that does not match.** A board fitted
  with a different crystal from the one an image was built for does not fall
  silent; it transmits at a proportionally different rate and the screen
  fills with bytes that nothing has reason to question. When a capture is
  mostly outside printable ASCII, the monitor now lists the crystals that
  would account for the rate the bytes arrived at, and points at **Tools →
  Clock**. `monitor` takes `--f-cpu` so it can do this on its own.

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
