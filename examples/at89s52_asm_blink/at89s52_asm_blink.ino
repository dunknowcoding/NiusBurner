/*
 * at89s52_asm_blink — toggle P1.0 from sdas8051 assembly.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Arduino IDE: after `python -m niusburner setup --board at89s52`, pick
 * Tools → Board → NiusBurner 8051 (SDCC) → AT89S52. This folder is a normal
 * sketch; cpl_p10.S appears as a second tab. Verify compiles, Upload flashes
 * the USB-ISP (erases the chip).
 *
 * The assembler is SDCC's sdas8051 (ASXXXX), not AVR GNU as. `cpl r16` and
 * `#include <avr/io.h>` will not assemble. C functions are `_name` in asm.
 *
 * Inline alternative in this .ino (also SDCC, not avr-gcc):
 *
 *     void loop(void) {
 *       __asm
 *         cpl P1.0
 *       __endasm;
 *       delay(200);
 *     }
 *
 *   python -m niusburner compile examples/at89s52_asm_blink --board at89s52
 *   python -m niusburner upload  examples/at89s52_asm_blink --board at89s52 --yes
 */

void cpl_p10(void);

void setup(void)
{
}

void loop(void)
{
    cpl_p10();
    delay(200);
}
