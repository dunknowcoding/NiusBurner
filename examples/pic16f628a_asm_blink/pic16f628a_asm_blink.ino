/*
 * pic16f628a_asm_blink — toggle RB2 from a PIC assembly unit.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Arduino IDE: after `python -m niusburner setup`, pick
 * Tools -> Board -> NiusBurner PIC (XC8) -> PIC16F628A. This folder is a
 * normal sketch; toggle_rb2.S appears as a second tab. Verify compiles,
 * Upload programs through the PICkit 3.
 *
 * The assembler is Microchip's, not AVR GNU as: PSECT and GLOBAL rather
 * than .section and .global, and a C function called `toggle_rb2` is
 * `_toggle_rb2` in assembly.
 *
 * Inline alternative, which needs no second tab:
 *
 *     void loop(void) {
 *       asm("BSF PORTB, 2");
 *       delay(100);
 *       asm("BCF PORTB, 2");
 *       delay(100);
 *     }
 *
 *   python -m niusburner compile examples/pic16f628a_asm_blink --board pic16f628a
 *   python -m niusburner upload  examples/pic16f628a_asm_blink --board pic16f628a --yes
 */

void toggle_rb2(void);

void setup(void)
{
    pinMode(10, OUTPUT);        /* port B (1), bit 2 */
}

void loop(void)
{
    toggle_rb2();
    delay(200);
}
