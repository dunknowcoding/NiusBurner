/*
 * niusdisplay_tm1637 — TM1637 clock with a UART banner for host checks.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * USB-ISP flashes the chip. CH341 on COM31 only reads this UART (115200 8N1).
 *
 *   python -m niusburner upload examples/niusdisplay_tm1637 --board at89s52 --yes
 *   python -m niusburner monitor --port COM31 --baud 115200 --seconds 4 --expect "NB TM1637"
 *
 * WIRING (8051 HAL: pin N is P1.N). ISP occupies P1.5/P1.6/P1.7.
 *   TM1637 CLK -> P1.0
 *   TM1637 DIO -> P1.1
 */

#include "NiusDuino.h"
#include "nd_tm1637.h"
#include "nius_serial.h"

#define CLK_PIN 0
#define DIO_PIN 1

static nd_tm1637 disp;
static unsigned char g_ok;

void setup(void)
{
    nius_serial_begin(115200UL);
    nius_serial_println_s("NB TM1637");
    g_ok = (unsigned char)(nd_tm1637_init(&disp, CLK_PIN, DIO_PIN, 4) == ND_OK);
    if (g_ok) {
        nd_tm1637_brightness(&disp, 3);
        nius_serial_println_s("INIT_OK");
    } else {
        nius_serial_println_s("INIT_FAIL");
    }
}

void loop(void)
{
    static nd_u8 hh = 12;
    static nd_u8 mm = 0;
    static nd_u8 colon = 1;

    nius_serial_println_s("NB TM1637");
    nius_serial_println_s(g_ok ? "INIT_OK" : "INIT_FAIL");

    if (g_ok) {
        nd_tm1637_show_time(&disp, hh, mm, colon);
        colon = (nd_u8)!colon;
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
    delay(500);
}
