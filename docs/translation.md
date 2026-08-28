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

`pgm_read_byte`, `pgm_read_word`, `pgm_read_dword`, `memcpy_P` and `strcpy_P`
are refused. They exist because AVR needs a separate instruction to reach
flash; the 8051 does not. Declare the table `__code` and index it:

```c
const __code unsigned char digits[] = { 0x3F, 0x06, 0x5B };
unsigned char d = digits[i];
```

### AVR-specific headers

`avr/io.h`, `avr/interrupt.h`, `avr/pgmspace.h`, `SoftwareSerial.h` and
`HardwareSerial.h` are refused, each with what to use instead.

## Timing

`delay()` and `delayMicroseconds()` are busy-wait loops calibrated against
`NIUS_FOSC` from two constants measured on silicon: the cost of one spin and
the fixed per-millisecond overhead. On an AT89S52 at 11.0592 MHz,
`delay(1000)` measures **997.3 ms**, about −0.3 %.

Three consequences worth knowing:

- **`millis()` only advances inside `delay()`.** No timer runs, so
  `while (millis() - start < 500) { }` never finishes. Use `delay()`.
- **Interrupts stretch delays.** The loop counts iterations, not time. Any
  interrupt handler you install is added to every delay.
- **`delayMicroseconds()` has about 190 µs of fixed cost.** One machine
  cycle is 1.085 µs at 11.0592 MHz, and the call itself has to scale its
  argument. Measured on an AT89S52, 1000 calls per sample:

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

The bit-banged buses are unaffected: I2C and SPI specify minimum times, not
exact ones, and both masters err slow. `Wire.setClock()` and
`SPI.setClockDivider()` are honoured as *ratios* — the absolute rate does not
match an AVR at the same setting, and cannot.

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
Measured on an AT89S52 build:

| sketch | flash | internal RAM |
|---|---|---|
| empty `setup()`/`loop()` | 734 B | 19 B |
| `examples/at89s52_serial` | 1336 B | 40 B |
| `examples/at89s52_registers` | 1429 B | 41 B |
| Wire + SPI + Serial + asm | 2492 B | 61 B |

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
python -m niusburner compile <sketch> --board at89s52 --debug-symbols
```

`lower` prints the translated C to stdout, so the output can be read, diffed
and compiled by hand. `--debug-symbols` keeps the symbol tables and listings
next to the image.
