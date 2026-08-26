/*
 * at89s52_blink — toggle P1.0.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pin 0 is P1.0 on the NiusBurner 8051 runtime (and on the NiusDisplay 8051
 * HAL). ISP uses P1.5/P1.6/P1.7; leave those for the dongle.
 *
 *   python -m niusburner setup --board at89s52
 *   python -m niusburner upload examples/at89s52_blink --board at89s52 --yes
 */

void setup(void)
{
    pinMode(0, OUTPUT);
}

void loop(void)
{
    digitalWrite(0, HIGH);
    delay(200);
    digitalWrite(0, LOW);
    delay(200);
}
