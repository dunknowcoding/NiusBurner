/*
 * Arduino-shaped C runtime for 8051 blink-and-GPIO sketches.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Timing is busy-wait, calibrated against NIUS_FOSC. A classic 8051 core
 * divides the crystal by 12, so one machine cycle is 12/Fosc -- 1.085 us at
 * 11.0592 MHz. The 1T parts divide by one instead; NIUS_CLOCKS_PER_MC
 * carries that. NIUS_SPIN_MC below is what one pass of nius_spin() costs in
 * machine cycles, fitted by timing delay(1000) over the UART; refit it if
 * the SDCC version or the memory model changes.
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
 * How many oscillator periods one machine cycle costs. A classic 8051
 * divides by 12; the 1T parts in this family run the same instruction set
 * at one clock per cycle, and everything below is written in machine
 * cycles, so this is the only place the difference belongs.
 *
 * It comes first because the two timing constants below depend on it: a
 * 1T core does not execute the same opcodes in the same number of cycles,
 * so the spin loop has to be measured separately on each generation.
 */
#ifndef NIUS_CLOCKS_PER_MC
#define NIUS_CLOCKS_PER_MC 12UL
#endif

/*
 * Two measured constants:
 *   NIUS_SPIN_MC      machine cycles one nius_spin() iteration costs
 *   NIUS_DELAY_MC_Q8  everything else one delay() iteration costs, in
 *                     1/256 machine cycles: the millis counter, the loop
 *                     test, and the fractional-spin carry
 *
 * Both are fitted by building delay() twice with the spin cost forced wide
 * apart and fitting a line through the two points. One point cannot do it:
 * a spin cheaper than assumed and an overhead dearer than assumed only ever
 * appear added together. They have to be refitted whenever the body of
 * delay() changes: adding the fractional carry moved the overhead from 39
 * to 65 machine cycles, and leaving it at 39 put delay(1000) at +2.48 %.
 *
 * Fitted on an AT89S52 at 11.0592 MHz (12 clocks per cycle), and again on
 * an STC8H1K08 at 24 MHz (1 clock per cycle), where the same source spins
 * in 14 cycles rather than 16. Carrying the 12-clock numbers onto a 1T part
 * put delay(1000) at 875.1 ms -- 12.5 % fast, and wrong in a way nothing
 * downstream could correct. The two 1T points were 875.1 ms at an assumed
 * 16 and 438.8 ms at an assumed 32, which fit S = 13.999 and an overhead of
 * 60.05 cycles.
 *
 * The overhead is carried in Q8 as well. As a whole number of machine
 * cycles it could only be tuned in steps of 1 cycle in 921.6, which is
 * 0.11 % -- coarser than the error being corrected. In Q8 the step is
 * 0.0004 %.
 */
#if NIUS_CLOCKS_PER_MC == 1
#ifndef NIUS_SPIN_MC
#define NIUS_SPIN_MC 14UL
#endif
#ifndef NIUS_DELAY_MC_Q8
#define NIUS_DELAY_MC_Q8 15374UL          /* 60.05 machine cycles */
#endif
#else
#ifndef NIUS_SPIN_MC
#define NIUS_SPIN_MC 16UL
#endif
#ifndef NIUS_DELAY_MC_Q8
#define NIUS_DELAY_MC_Q8 16428UL          /* 64.17 machine cycles */
#endif
#endif

#define NIUS_CLOCKS_PER_MS (NIUS_CLOCKS_PER_MC * 1000UL)

#define NIUS_MC_PER_MS    (NIUS_FOSC / NIUS_CLOCKS_PER_MS)

/*
 * Machine cycles per millisecond is not an integer: 11.0592 MHz gives 921.6,
 * and every stage that rounded it away cost accuracy that could not be
 * recovered later. Carry it in Q8 instead, computed without overflowing a
 * 32-bit constant expression at any clock this part can run.
 */
#define NIUS_MC_PER_MS_Q8 (((NIUS_FOSC / NIUS_CLOCKS_PER_MS) * 256UL) + (((NIUS_FOSC % NIUS_CLOCKS_PER_MS) * 256UL) / NIUS_CLOCKS_PER_MS))

/* What is left for spinning once the loop's own overhead is paid, Q8. */
#define NIUS_SPIN_BUDGET_Q8 (NIUS_MC_PER_MS_Q8 - NIUS_DELAY_MC_Q8)

/* Spins per millisecond, Q8, then split into whole spins and a remainder.
   delay() adds the remainder up and spends it as a whole spin whenever it
   reaches one, so the truncation does not accumulate over a long wait. */
#define NIUS_SPINS_PER_MS_Q8 (NIUS_SPIN_BUDGET_Q8 / NIUS_SPIN_MC)
#define NIUS_SPINS_PER_MS    (NIUS_SPINS_PER_MS_Q8 / 256UL)
#define NIUS_SPIN_FRAC_Q8    (NIUS_SPINS_PER_MS_Q8 - (NIUS_SPINS_PER_MS * 256UL))

/* Spins per microsecond, Q16, so delayMicroseconds() needs no division at
   run time. Derived from the Q8 cycle count, not from the rounded one. */
#define NIUS_SPINS_PER_US_Q16 ((NIUS_MC_PER_MS_Q8 * 256UL) / (1000UL * NIUS_SPIN_MC))

/*
 * Q16 runs out of headroom as soon as the part spins more than once per
 * microsecond, which a 1T core does above about 16 MHz: the scale itself
 * stops fitting in the 16 bits the multiply is built around. Past that
 * point range matters more than the sixteenth bit of a fraction, so the
 * scale drops to Q8 -- still 0.3 % on a 22.1184 MHz part, and it reaches
 * 255 spins per microsecond before it runs out again.
 */
#if NIUS_SPINS_PER_US_Q16 > 0xFFFFUL
#define NIUS_US_SHIFT 8
#define NIUS_SPINS_PER_US_SCALE (NIUS_MC_PER_MS_Q8 / (1000UL * NIUS_SPIN_MC))
#else
#define NIUS_US_SHIFT 16
#define NIUS_SPINS_PER_US_SCALE NIUS_SPINS_PER_US_Q16
#endif

/* The multiply in delayMicroseconds() is only safe while this holds. */
#if NIUS_SPINS_PER_US_SCALE > 0xFFFFUL
#error "NIUS_FOSC too high for the delayMicroseconds scale"
#endif

static unsigned char g_p1 = 0xFF;
static unsigned char g_p2 = 0xFF;
#ifdef NIUS_ISP_ENTRY
/*
 * SDCC only emits an interrupt vector in the module being compiled, so an
 * ISR defined elsewhere needs its prototype visible *here*, where main()
 * is, or nothing is placed at 0x0023. Without this the part jumps into
 * whatever happens to be at that address the moment the serial interrupt
 * is enabled, which is immediately: begin() leaves TI set. The symptom is
 * a board that looks unpowered because it dies before printing a byte.
 */
void nius_isp_entry_isr(void) __interrupt(4);
#endif

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
     * cycles, over a millisecond. That made delayMicroseconds(50) take
     * 1206 us and delayMicroseconds(250) take 1488 us -- 24x and 6x their
     * arguments. Q16 turns it into one 16x16
     * multiply and a byte select.
     */
#if NIUS_US_SHIFT == 16
    /* us is 16 bit, so the product shifted back down can never exceed the
       Q16 constant itself -- the old paging loop over 0xFFFF was dead code
       whose 32-bit comparison ran on every call. */
    unsigned int spins =
        (unsigned int)(((unsigned long)us * NIUS_SPINS_PER_US_SCALE) >> 16);

    if (spins)
        nius_spin(spins);
#else
    /*
     * On the Q8 scale the bound above no longer holds: a 1T part fast
     * enough to need Q8 also wants more than 65535 spins for a long
     * argument, so the count is spent in pages. The comparison is back,
     * but only on the parts that actually need it.
     */
    unsigned long spins =
        ((unsigned long)us * NIUS_SPINS_PER_US_SCALE) >> 8;

    while (spins > 0xFFFFUL) {
        nius_spin(0xFFFFU);
        spins -= 0xFFFFUL;
    }
    if (spins)
        nius_spin((unsigned int)spins);
#endif
}

void delay(unsigned int ms)
{
    /*
     * Spins per millisecond is fractional -- 55.16 on an AT89S52 at
     * 11.0592 MHz -- and spending only the whole part of it lost 0.28 % on
     * every millisecond, the same way every time. The remainder is carried
     * here instead and spent as one extra spin whenever it adds up to one,
     * which brings the error down to the resolution of a single spin.
     */
    unsigned int frac = 0;

    while (ms--) {
        unsigned int spins = NIUS_SPINS_PER_MS;

        frac += NIUS_SPIN_FRAC_Q8;
        if (frac >= 256U) {
            frac -= 256U;
            spins++;
        }
        nius_spin(spins);
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
