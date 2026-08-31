# Arduino C++ to C: what is translated, and what is not

SDCC has no C++ mode. The Arduino IDE writes C++. NiusBurner closes that gap
by rewriting the Arduino *shape* of a sketch into C before SDCC sees it.

This is a **facade translator**, not a C++ compiler. It rewrites the API
surface an Arduino sketch actually uses — `Serial`, `Wire`, `SPI`, `F()`,
library objects — and refuses everything whose meaning C cannot carry. The
rule it follows is worth stating once, because everything below follows from
it:

> Anything that would change *when* code runs, *how many times* it runs, or
> *what it computes*, is refused rather than approximated.

A refusal says which of three things is wrong, because the fix differs:

| Message | Meaning |
|---|---|
| *uses C++ that SDCC cannot compile* | the language; rewrite it in C |
| *cannot run on this part* | the peripheral is missing; change board or wiring |
| *uses an Arduino API this runtime does not provide* | the call, with the 8051 spelling to use instead |

These checks run on **every** sketch, including one written in plain C with
no C++ in it anywhere. A missing peripheral is missing either way.

An approximation that compiles and then misbehaves on hardware is worse than
a refusal that names the problem.

## The three guarantees

**Assembly is never read.** `__asm … __endasm`, `_asm … _endasm`,
`asm("…")` and `__asm__ volatile("…")` are stepped over by every rewrite
pass and reach the compiler byte for byte. A hand-counted delay stays exactly
as many cycles as it was written to be. Sibling `.S` / `.s` / `.asm` files in
a sketch folder are assembled with `sdas8051` and never touched at all.

**Registers are never renamed.** `P1`, `P3`, `TMOD`, `SCON`, `TH1`, `P1_0`
and every other SFR name comes from `<8052.h>`, which the sketch runtime
already includes. The translator does not know those names and does not
rewrite them. `P1 |= 0x10;` compiles to `orl P1,#0x10`.

**Arguments are evaluated once.** A library call that expands to a form using
an argument twice is refused when the argument has side effects, rather than
running it twice:

```cpp
lcd.print(buffer[i++]);   // refused: i++ would be evaluated twice
```

`examples/at89s52_registers` exercises all three in one sketch.

## What is translated

| Arduino | becomes | notes |
|---|---|---|
| `setup()` / `loop()` | `void setup(void)` / `void loop(void)` plus a generated `main()` | |
| `Serial.begin/print/println/write/read/available/flush/end` | the hardware UART on P3.0/P3.1 | |
| `F("text")` | a plain string literal | SDCC already keeps literals in code space |
| `Wire.*` | a bit-banged I2C master | master only, 7-bit addresses |
| `SPI.*` | a bit-banged SPI master | all four modes, both bit orders |
| `pinMode` / `digitalWrite` / `digitalRead` | port latch reads and writes | pins 0–7 are P1.0–P1.7, 8–15 are P2.0–P2.7 |
| `delay` / `delayMicroseconds` / `millis` | calibrated busy-wait | see *Timing* below |
| `map` / `constrain` / `min` / `max` / `abs` / `bitRead` / `bitSet` / … | the same macros and functions | `min`/`max`/`abs` stay macros, so they double-evaluate exactly as they do on AVR |
| `shiftOut` / `shiftIn` / `random` / `randomSeed` | C equivalents | linked only if called |
| `true` / `false` / `bool` / `uint8_t` / … | `1` / `0` / `unsigned char` / … | |
| `byte` / `word` / `nullptr` / `NULL` / `_BV()` / `LED_BUILTIN` / `PI` … | the AVR core's own definitions | `LED_BUILTIN` is P1.0 by convention; override it |
| `memcpy` / `memset` / `strlen` / `sprintf` … | themselves | `<string.h>` and `<stdio.h>` are already included |
| `interrupts()` / `noInterrupts()` | `EA = 1` / `EA = 0` | the zero-argument form only |
| `Serial.print(x)` of any width | the right routine for x's type | see *Widths* below |
| `struct Point { … }; Point p;` | the same, plus `typedef struct Point Point;` | C needs the tag or a typedef; the layout is untouched |
| NiusDisplay `NiusSegment` / `NiusCharLCD` / `NiusMatrix` | the library's portable C core | see *Libraries* |

## What is refused, and why

### Real C++

`class`, `template`, `namespace`, `new` / `delete`, `String`, `operator`,
`virtual`, `try` / `catch` / `throw`, `static_cast<>` and friends, `enum
class`, `auto x =`, references (`int &x`), and `::` anywhere.

There is no honest C spelling for a virtual call or a destructor. A sketch
that needs them belongs on a part with a C++ compiler.

Syntax that C simply rejects — default arguments, function overloads — is
**not** listed here on purpose. SDCC rejects it with a file and line number,
which is more useful than a second opinion from the translator.

### Peripherals the part does not have

`python -m niusburner boards --features` prints the table. For every board
each peripheral is one of:

- **hardware** — the silicon has it
- **software** — it does not, but NiusBurner bit-bangs it and the Arduino
  facade works
- **none** — neither

A classic 8051 (AT89S51/S52, STC89C52RC, AT89C2051) is:

| gpio | uart | i2c | spi | pwm | adc | eeprom |
|---|---|---|---|---|---|---|
| hardware | hardware | software | software | none | none | none |

So `Wire` and `SPI` work — that is the whole point of shipping bit-banged
masters — and `analogWrite`, `analogRead`, `tone`, `Servo.h` and `EEPROM.h`
are refused. Software PWM is possible in principle, but only with a timer
interrupt firing through the same code that bit-bangs I2C and SPI, which
retimes every transfer in the sketch. That is the "changes when code runs"
case, so it is refused.

### Things with no timebase

`micros()`, `pulseIn()` and `pulseInLong()` need a free-running microsecond
counter. No timer is started by the runtime, so all three are refused instead
of returning a number that never advances. `attachInterrupt()` is refused
with the SDCC spelling in the message: `void on_int0(void) __interrupt(0)
{ … }`.

`interrupts()` and `noInterrupts()` are **not** refused — on an 8051 they are
exactly the global enable bit, so they lower to `EA = 1` and `EA = 0`. Only
the zero-argument Arduino spelling is rewritten, so a function of your own
called `interrupts(n)` is left alone.

### Floating point

`pow`, `sqrt`, `sin`, `cos`, `floor`, `fabs` and the rest of `<math.h>` are
refused. SDCC can compile them, but each one pulls in the soft-float library,
which does not fit next to a sketch in 8 KB and has no fixed cost to reason
about. Use integer arithmetic, or a lookup table declared `__code`.

### AVR program-memory addressing

`PROGMEM`, `PGM_P`, `pgm_read_byte`, `pgm_read_word`, `pgm_read_dword`,
`memcpy_P` and `strcpy_P` are refused. They exist because AVR needs a
separate instruction to reach flash; the 8051 does not. Declare the table
`__code` and index it:

```c
const __code unsigned char digits[] = { 0x3F, 0x06, 0x5B };
unsigned char d = digits[i];
```

### AVR-specific headers

`avr/io.h`, `avr/interrupt.h`, `avr/pgmspace.h`, `SoftwareSerial.h` and
`HardwareSerial.h` are refused, each with what to use instead.

## Timing

`delay()` and `delayMicroseconds()` are busy-wait loops calibrated against
`NIUS_FOSC` from two fitted constants: the cost of one spin and
the fixed per-millisecond overhead. On an AT89S52 at 11.0592 MHz,
`delay(1000)` measures **997.3 ms**, about −0.3 %.

Three consequences worth knowing:

- **`millis()` only advances inside `delay()`.** No timer runs, so
  `while (millis() - start < 500) { }` never finishes. Use `delay()`.
- **Interrupts stretch delays.** The loop counts iterations, not time. Any
  interrupt handler you install is added to every delay.
- **`delay()` is within 0.03 %.** On an AT89S52 at 11.0592 MHz,
  `delay(1000)` is 999.7 ms. Spins per millisecond is fractional -- 53.72 --
  and spending only its whole part cost 0.28 % on every millisecond, always
  in the same direction; the remainder is carried and spent as one extra
  spin whenever it adds up to one. The per-iteration overhead is carried in
  1/256ths of a machine cycle for the same reason: as a whole number it
  could only be tuned in steps of 0.11 %, coarser than the error being
  corrected.
- **`delayMicroseconds()` has about 190 µs of fixed cost.** One machine
  cycle is 1.085 µs at 11.0592 MHz, and the call itself has to scale its
  argument. On an AT89S52, 1000 calls per sample:

  | asked | actual | note |
  |---|---|---|
  | 50 µs | 240 µs | overhead dominates |
  | 100 µs | 292 µs | |
  | 250 µs | 448 µs | |
  | 1000 µs | 1195 µs | +19 % |

  The slope is right — every microsecond asked for beyond the fixed cost
  arrives — so a caller who subtracts the overhead gets what it wants. Below
  roughly 500 µs the overhead is most of the wait, and the honest tool is
  inline assembly, which the translator passes through untouched.
  `examples/at89s52_registers` counts out twelve cycles that way.

### The bit-banged buses

I2C and SPI specify minimum times, not exact ones, and both masters err
slow, so a slow bus is a correct bus. How slow is worth knowing:

| setting | measured | vs the fastest setting |
|---|---|---|
| `setClock(400000)` / `setClock(100000)` | 1061 µs per transaction | — |
| `setClock(50000)` | 1347 µs | +286 µs |
| `setClock(25000)` | 1920 µs | +860 µs |
| `setClock(10000)` | 3066 µs | +2006 µs |

A transaction there is START, nine bits of address and ACK slot, then STOP.
The steps are exactly linear in the setting (286 µs, 3×, 7×), and the two
fastest requests land in the same band because both ask for more than the
part can do.

| `setClockDivider` | measured per bit | vs DIV2 |
|---|---|---|
| `SPI_CLOCK_DIV2` | 190 µs | — |
| `SPI_CLOCK_DIV4` | 216 µs | +26 µs |
| `SPI_CLOCK_DIV8` | 268 µs | +78 µs |
| `SPI_CLOCK_DIV16` | 372 µs | +182 µs |
| `SPI_CLOCK_DIV64` | 997 µs | +807 µs |

Two things follow. The *ratios* between settings hold and the steps are
exact, so a device that needs a slower bus gets one. But the floor is set by
the bit loop rather than by the requested rate: roughly 108 machine cycles
per I2C bit and 175 per SPI bit, of which the deliberate delay is 15. So the
fastest SCL available is about 8.5 kHz and the fastest SCK about 5 kHz,
whatever the sketch asks for. Both are far below what the same call gives on
an AVR, and a sketch with a timeout that assumes 100 kHz will notice.

Those floors came down about 17 % by addressing the pins as bits. Driving a
line was a helper function taking a level and branching on it, called three
times per bit; `setb` and `clr` on a bit-addressable SFR are one cycle and
two bytes. Hoisting the SPI mode flags into locals was tried next and made
it *worse* -- two more live values push SDCC past what it can keep in
registers, and the measured bit period went from 190 µs to 204 µs while the
code grew 23 bytes. It was reverted on the evidence, and the comment in
`nius_spi.c` says so, so the next person does not repeat it.

The half-bit delay itself is exact. It is assembly, not a C loop, and it
costs `15 + 8 × step` machine cycles by construction:

```
push ar7   2      mov r7,_g_extra  2      loop: nop ×6  6
mov  a,r7  1      jz   done        2            djnz    2      pop ar7  2
```

It was a C `while (n--)` around a nop block, whose own cost was whatever
SDCC emitted that day. An earlier attempt to keep the counter in a register
assumed the local landed in DPL; it was actually in r7, which would have
looped an arbitrary number of times. The register is saved and the counter
is read straight from the global now, because SDCC's allocation is not part
of the contract.

## Widths

C has no overloading, so a number reaching `Serial.print` used to be cast to
`int` — 16 bits, signed — whatever it actually was. That silently destroyed
values: `Serial.println(millis())` went negative after 32.7 seconds and
wrapped to zero after 65.5, and `Serial.println(70000)` printed 4464.

The generated call carries no cast now. `nius_serial.h` resolves the type
with `_Generic`, which SDCC supports: `unsigned long` gets its own routine
and everything narrower converts to `long` without losing a value.
`4000000000`, `EE6B2800`, `-70000`, `65000`, `200` and `70000` all print
correctly, and `'A'` still prints as a character rather than 65.

Floating point has no printer at all, deliberately. A float reaching
`Serial.print` would otherwise be converted to an integer and quietly lose
its fraction.

The casts the library facades apply are each the Arduino signature for that
call — `Wire.write(uint8_t)`, `SPI.transfer(uint8_t)` — so a value too wide
for the call truncates exactly where it truncates on an AVR, and nowhere
else.

## Libraries

A library is translated when its tree contains
`<Library>/niusburner/adapter.json`. NiusBurner never imports the library; it
reads that file and the C support sources beside it. Two are bundled:

```
niusburner/adapters/
  Arduino/        adapter.json + mcs51/  Serial, Wire, SPI, the core API
  NiusDisplay/    adapter.json + mcs51/  NiusSegment, NiusCharLCD, NiusMatrix
```

Each facade declares what it needs. `NiusCharLCD` requires `i2c`,
`NiusMatrix` requires `spi`, `NiusSegment` needs only `gpio` — so all three
work on an AT89S52, over bit-banged buses. `NiusTFT`, `NiusOLED`,
`NiusTouch` and `NiusSurface` are refused: they are `Print`/graphics C++, and
the framebuffers want XRAM a minimum DIP-40 board does not have.

Dropping an `adapter.json` into another library is enough to add it. No
change to `cxxlower.py`.

## Size

SDCC links whole modules, so anything sharing a translation unit with
`pinMode()` costs flash in every sketch. The Arduino API is therefore split
across several units and only the ones a sketch actually calls are linked.
On an AT89S52 build:

| sketch | flash | internal RAM |
|---|---|---|
| empty `setup()`/`loop()` | 592 B | 19 B |
| `examples/at89s52_serial` | 1512 B | 67 B |
| `examples/at89s52_registers` | 1619 B | 68 B |
| Wire + SPI + Serial + asm | 2045 B | 78 B |

The serial figures grew when printing stopped truncating: a 32-bit digit
routine and its buffer cost about 180 bytes of flash and 27 of internal RAM
over the 16-bit one it replaced. That is the price of `println(millis())`
being right, and it is the trade this tool makes every time.

`--optimize size` (the default), `speed`, or `none` chooses what SDCC spends
its effort on. `size` is the default because these parts run out of flash
long before they run out of cycles. Every build prints what it used against
what the part has.

## When the translation is wrong

It should refuse, not miscompile. If a sketch lowers and then misbehaves on
hardware, that is a bug worth reporting with the sketch attached. Two things
make it easy to see what the translator did:

```bash
python -m niusburner lower <sketch> --board at89s52     # the C it produced
```

`lower` prints the translated C to stdout, so the output can be read, diffed
and compiled by hand.
