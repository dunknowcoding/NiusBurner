/*
 * niusdisplay_tm1637 — a counting clock on a 4-digit module.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * C that reads like a sketch. SDCC cannot compile the Arduino C++ facade
 * (NiusDisplay.h / NiusSegment); this is the same program against the C API.
 *
 * WIRING (8051 HAL: pin N is P1.N)
 *   TM1637 CLK -> P1.0    (pin 0)
 *   TM1637 DIO -> P1.1    (pin 1)
 *   VCC, GND
 *
 * This is not I2C. Do not share a hardware I2C peripheral.
 *
 *   python -m niusburner upload examples/niusdisplay_tm1637 --board at89s52 --yes
 *
 * NiusDisplay is found as a sibling of this repo, via NIUSDISPLAY, or
 * --library. A minimum AT89S52 board has no XRAM; this sketch stays in IRAM.
 */

#include "NiusDuino.h"
#include "nd_tm1637.h"

#define CLK_PIN 0
#define DIO_PIN 1

static nd_tm1637 disp;

void setup(void)
{
    if (nd_tm1637_init(&disp, CLK_PIN, DIO_PIN, 4) != ND_OK) {
        for (;;) {
            /* module did not ACK: swapped CLK/DIO, no power, or no pull-ups */
        }
    }
    nd_tm1637_brightness(&disp, 3);
}

void loop(void)
{
    static nd_u8 hh = 12;
    static nd_u8 mm = 0;
    static nd_u8 colon = 1;

    nd_tm1637_show_time(&disp, hh, mm, colon);
    colon = (nd_u8)!colon;
    delay(500);

    if (!colon) {
        mm = (nd_u8)(mm + 1);
        if (mm >= 60) {
            mm = 0;
            hh = (nd_u8)(hh + 1);
            if (hh >= 24)
                hh = 0;
        }
    }
}
