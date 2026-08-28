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

/* Spins per microsecond, Q16 fixed point, so delayMicroseconds() needs no
   division at run time. 65536 keeps the rounding error under 0.01 %. */
#define NIUS_SPINS_PER_US_Q16     (((NIUS_MC_PER_MS) * 65536UL) / (1000UL * NIUS_SPIN_MC))

/* The cast in delayMicroseconds() is only safe while this holds. */
#if NIUS_SPINS_PER_US_Q16 > 0xFFFFUL
#error "NIUS_FOSC too high for the Q16 delayMicroseconds scale"
#endif

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
     * single microsecond is below what a C loop can resolve.
     *
     * The scale factor is folded by the preprocessor. It used to be a
     * 32-bit divide done here, at run time, and this core has no divide
     * instruction: SDCC calls a routine costing about a thousand machine
     * cycles, over a millisecond. Measured on silicon, that made
     * delayMicroseconds(50) take 1206 us and delayMicroseconds(250) take
     * 1488 us -- 24x and 6x their arguments. Q16 turns it into one 16x16
     * multiply and a byte select.
     */
    /* us is 16 bit, so the product shifted back down can never exceed the
       Q16 constant itself -- the old paging loop over 0xFFFF was dead code
       whose 32-bit comparison ran on every call. */
    unsigned int spins =
        (unsigned int)(((unsigned long)us * NIUS_SPINS_PER_US_Q16) >> 16);

    if (spins)
        nius_spin(spins);
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
