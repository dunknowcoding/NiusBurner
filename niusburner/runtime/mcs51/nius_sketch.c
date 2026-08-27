/*
 * Arduino-shaped C runtime for 8051 blink-and-GPIO sketches.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Timing is busy-wait, calibrated against NIUS_FOSC. The 8051 core divides
 * the crystal by 12, so one machine cycle is 12/Fosc -- 1.085 us at
 * 11.0592 MHz. NIUS_SPIN_MC below is what one pass of nius_spin() costs in
 * machine cycles, measured on the bench by timing delay(1000) over the UART;
 * re-measure it if the SDCC version or the memory model changes.
 *
 * There are no timers here on purpose: a sketch is free to use all three.
 * That makes delay() sensitive to interrupts, which is the same trade the
 * NiusDisplay 8051 HAL makes.
 */

#include "nius_sketch.h"

#ifdef __SDCC
#include <8052.h>
#endif

#define PORT_OF(p) ((p) >> 3)
#define BIT_OF(p)  ((p) & 7)

#ifndef NIUS_FOSC
#define NIUS_FOSC 11059200UL
#endif

/*
 * Two measured constants, from timing delay(1000) on an AT89S52 at
 * 11.0592 MHz with two different spin counts and fitting a line:
 *   NIUS_SPIN_MC   machine cycles one nius_spin() iteration costs
 *   NIUS_DELAY_MC  everything else one delay() iteration costs, which is
 *                  the millis counter update and the loop test
 * Subtracting the second is what takes delay(1000) from +3.2 % to -0.3 %.
 */
#ifndef NIUS_SPIN_MC
#define NIUS_SPIN_MC 16UL
#endif
#ifndef NIUS_DELAY_MC
#define NIUS_DELAY_MC 39UL
#endif

#define NIUS_MC_PER_MS    (NIUS_FOSC / 12000UL)
#define NIUS_SPINS_PER_MS ((NIUS_MC_PER_MS - NIUS_DELAY_MC) / NIUS_SPIN_MC)

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

static void nius_spin(unsigned int n)
{
    /* volatile: the loop body is empty and the count is dead afterwards, so
       without it SDCC is entitled to delete the whole delay. */
    volatile unsigned int i = n;
    while (i)
        i--;
}

void delayMicroseconds(unsigned int us)
{
    /*
     * One machine cycle is already about 1.085 us at 11.0592 MHz, so a
     * single microsecond is below what a C loop can resolve. Calls under
     * roughly 50 us are dominated by the arithmetic below and round up.
     */
    /* Scaled through NIUS_MC_PER_MS, not NIUS_SPINS_PER_MS: the per-
       millisecond overhead is not paid here, and us * Fosc would overflow. */
    unsigned long spins =
        ((unsigned long)us * NIUS_MC_PER_MS) / (1000UL * NIUS_SPIN_MC);

    while (spins > 0xFFFFUL) {
        nius_spin(0xFFFF);
        spins -= 0xFFFFUL;
    }
    if (spins)
        nius_spin((unsigned int)spins);
}

void delay(unsigned int ms)
{
    while (ms--) {
        nius_spin(NIUS_SPINS_PER_MS);
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
