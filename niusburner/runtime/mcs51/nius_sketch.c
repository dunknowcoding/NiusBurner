/*
 * Arduino-shaped C runtime for 8051 blink-and-GPIO sketches.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Timing is uncalibrated busy-wait, same honest limitation as nd_hal_8051.
 * A crystal change changes the blink rate; that is expected.
 */

#include "nius_sketch.h"

#ifdef __SDCC
#include <8052.h>
#endif

#define PORT_OF(p) ((p) >> 3)
#define BIT_OF(p)  ((p) & 7)

static unsigned char g_p1 = 0xFF;
static unsigned char g_p2 = 0xFF;
static unsigned long g_ms;

void pinMode(unsigned char pin, unsigned char mode)
{
    /*
     * Classic 8051 ports are quasi-bidirectional: writing 1 drives high
     * weakly and enables input. There is no direction register.
     */
    if (mode != OUTPUT)
        digitalWrite(pin, HIGH);
}

void digitalWrite(unsigned char pin, unsigned char value)
{
#ifdef __SDCC
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));
    if (PORT_OF(pin) == 0) {
        if (value) g_p1 |= mask; else g_p1 &= (unsigned char)~mask;
        P1 = g_p1;
    } else {
        if (value) g_p2 |= mask; else g_p2 &= (unsigned char)~mask;
        P2 = g_p2;
    }
#else
    (void)pin;
    (void)value;
#endif
}

unsigned char digitalRead(unsigned char pin)
{
#ifdef __SDCC
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));
    return (unsigned char)(((PORT_OF(pin) == 0 ? P1 : P2) & mask) ? 1 : 0);
#else
    (void)pin;
    return 0;
#endif
}

void delayMicroseconds(unsigned int us)
{
    unsigned int i;
    while (us--) {
        for (i = 0; i < 1; i++) {
            /* spin */
        }
    }
}

void delay(unsigned int ms)
{
    while (ms--) {
        delayMicroseconds(1000);
        g_ms++;
    }
}

unsigned long millis(void)
{
    return g_ms;
}

#ifdef ND_NIUS_SKETCH_MAIN
int main(void)
{
    setup();
    for (;;)
        loop();
}
#endif
