# Assembly

Assembly is never read, rewritten or reformatted. The translator steps over
every assembly construct it meets and hands it to the assembler exactly as
written, so a hand-counted delay stays hand-counted and a register write
stays a register write.

That makes assembly the escape hatch for the two things C cannot promise on
these parts: **exact instruction timing**, and **a specific encoding**.

Two ways in, on both families: a whole file, or a block inside C.

---

## A whole file

Drop a `.S`, `.s` or `.asm` file beside the `.ino`. In the Arduino IDE it
appears as a second tab; from the command line it is picked up automatically.
Nothing needs declaring — it becomes another translation unit, and the sketch
calls into it with an ordinary prototype.

Working examples:

| | |
|---|---|
| [`examples/at89s52_asm_blink/`](../examples/at89s52_asm_blink/) | 8051, `cpl_p10.S` |
| [`examples/pic16f628a_asm_blink/`](../examples/pic16f628a_asm_blink/) | PIC, `toggle_rb2.S` |

**A C function called `name` is `_name` in assembly.** Both toolchains
prefix an underscore, and forgetting it is the usual cause of "undefined
symbol" at link time.

### 8051 — sdas8051 (ASXXXX syntax)

```asm
        .module cpl_p10
        .optsdcc -mmcs51 --model-small

        .globl  _cpl_p10
        .area   CSEG (CODE)

P1      = 0x0090

_cpl_p10:
        cpl     P1.0
        ret
```

The `.optsdcc` line has to match the model the rest of the build uses, and
SFR names are not predefined — `P1` is given its address here.

### PIC — the Microchip assembler

```asm
    GLOBAL  _toggle_rb2
    PSECT   text_toggle,local,class=CODE,delta=2

_toggle_rb2:
    MOVLW   0x04
    XORWF   6, 1        ; PORTB at 0x06, bank 0
    RETURN
```

`delta=2` says the section is word-addressed, which is what mid-range PIC
program memory is. Leaving it out gives a linker error about odd addresses.

---

## A block inside C

Shorter, and it keeps the code next to what it is for.

### 8051

```c
void loop(void) {
  __asm
    cpl  P1.0
  __endasm;
  delay(200);
}
```

### PIC

```c
void loop(void) {
  asm("BSF PORTB, 2");
  delay(100);
  asm("BCF PORTB, 2");
  delay(100);
}
```

`__asm … __endasm`, `asm("…")` and `__asm__ volatile("…")` are all
recognised and stepped over.

---

## It is not AVR assembly

This is the mistake that costs the most time. Sketches copied from an
Arduino Uno will not assemble:

| Written for AVR | Why it fails here |
|---|---|
| `#include <avr/io.h>` | An AVR header. Neither part has one. |
| `ldi r16, 0xFF` | AVR registers. The 8051 has A/B/R0–R7; the PIC has W and file registers. |
| `.global`, `.section` | GNU as directives. Use `.globl`/`.area` (8051) or `GLOBAL`/`PSECT` (PIC). |
| `sbi PORTB, 5` | An AVR instruction. |

There is no translation layer for this and there will not be one: silently
reinterpreting someone's hand-written assembly is exactly the kind of thing
this tool refuses to do.

---

## Uploading it

Nothing changes. An assembly sketch is a sketch:

```bash
python -m niusburner upload examples/at89s52_asm_blink --board at89s52 --yes
python -m niusburner upload examples/pic16f628a_asm_blink --board pic16f628a --yes
```

or **Verify** then **Upload** in the IDE, with the same board and programmer
menus as any other sketch. See [arduino-ide.md](arduino-ide.md).

---

## Registers without assembly

Most of what people reach for assembly to do is a register write, and that
needs no assembly at all. Special-function registers are ordinary names in C,
and the translator passes those through untouched too:

```c
void setup(void) {
  P1 = 0x00;          /* 8051: whole port low */
  TMOD = 0x20;
  TRISB = 0x00;       /* PIC: port B all outputs */
  PORTB = 0xFF;
}
```

[`examples/at89s52_registers/`](../examples/at89s52_registers/) does this
throughout, and counts out an exact delay in inline assembly where the timing
has to be exact.

For what the C side guarantees about timing, and where it does not, see
[translation.md](translation.md).
