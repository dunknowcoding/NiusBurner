/*
 * The Arduino API on a 16-bit PIC (dsPIC30F).
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Three things differ from the 8-bit parts enough to be worth stating.
 *
 * Ports are 16 bits wide and they are not a contiguous run: a dsPIC30F4013
 * brings out A, B, C, D and F, with no E. A count of ports cannot describe
 * that, so the catalog hands this file a bit mask instead and each port is
 * compiled in only if its bit is set. Naming a port the part does not have
 * is a compile error, not a pin that quietly does nothing.
 *
 * Writes go to the latch. LATx exists precisely so that a read-modify-write
 * on a pin the outside world is also driving cannot corrupt its neighbours,
 * which is the classic PIC read-modify-write hazard.
 *
 * Timing comes from XC16's __delay_ms and __delay_us, which are cycle
 * counts the compiler computes from FCY -- the instruction rate, which on
 * this family is Fosc/4. They take a compile-time constant, so the
 * millisecond loop calls __delay_ms(1) repeatedly, exactly as the 8-bit
 * runtimes do, and millis() advances inside delay() and nowhere else.
 */

#include "nius_sketch.h"

#include <xc.h>

#ifndef NIUS_FOSC
#define NIUS_FOSC 7372800UL
#endif

/* The instruction clock. A dsPIC30F executes one instruction every four
   oscillator periods, and libpic30's delays are written in terms of it. */
#ifndef FCY
#define FCY (NIUS_FOSC / 4UL)
#endif

#include <libpic30.h>

/* Which ports the package bonds out, one bit each: A is 1, B is 2, C is 4,
   D is 8, E is 16, F is 32, G is 64. */
#ifndef NIUS_PIC24_PORTS
#define NIUS_PIC24_PORTS 0x2FU          /* A B C D F, the 40-pin default */
#endif

#define NIUS_HAS_PORT(bit) (NIUS_PIC24_PORTS & (bit))

/*
 * Configuration.
 *
 * A dsPIC30F latches its oscillator, watchdog and code protection from
 * words at 0xF80000 upwards, and an image that leaves them out is
 * programmed onto whatever the erased part holds. The setting names come
 * from the compiler's own configuration tables, not from a datasheet
 * reading: FOSFPR selects the oscillator, FCKSMEN the clock switch and
 * monitor, WDT the watchdog.
 *
 * The watchdog is the one that matters most: nothing here clears it, so a
 * sketch built with it on would reset in the middle of its own loop().
 *
 * XT covers a 4-10 MHz crystal and HS goes above that, which is the same
 * split the 8-bit runtimes make. A sketch that wants its own settings
 * defines NIUS_NO_CONFIG and supplies a complete set.
 */
#ifndef NIUS_PIC24_CONFIG
#define NIUS_PIC24_CONFIG 1
#endif

#ifndef NIUS_NO_CONFIG

#if NIUS_PIC24_CONFIG == 2
/*
 * Some members of the family split the oscillator across two settings --
 * FOS picks the source, FPR picks which primary mode -- while the rest
 * fold both into FOSFPR. The choice is identical either way; only the
 * spelling differs, and naming the wrong one is a compile error.
 */
#pragma config FOS = PRI
#if NIUS_FOSC > 10000000UL
#pragma config FPR = HS
#else
#pragma config FPR = XT
#endif
#else
#if NIUS_FOSC > 10000000UL
#pragma config FOSFPR = HS
#else
#pragma config FOSFPR = XT
#endif
#endif

#pragma config FCKSMEN = CSW_FSCM_OFF
#pragma config WDT = WDT_OFF
#pragma config FPWRT = PWRT_64
#pragma config BOREN = PBOR_ON
#pragma config MCLRE = MCLR_EN
#pragma config GWRP = GWRP_OFF
#pragma config GCP = CODE_PROT_OFF

#endif /* NIUS_NO_CONFIG */

static unsigned long g_ms;
static unsigned long g_seed = 1;

#define PORT_OF(p) ((unsigned char)((p) >> 4))
#define BIT_OF(p)  ((unsigned char)((p) & 15))

void pinMode(unsigned char pin, unsigned char mode)
{
    unsigned int mask = (unsigned int)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
#if NIUS_HAS_PORT(0x01)
    case 0: if (mode == OUTPUT) TRISA &= (unsigned int)~mask; else TRISA |= mask; break;
#endif
#if NIUS_HAS_PORT(0x02)
    case 1: if (mode == OUTPUT) TRISB &= (unsigned int)~mask; else TRISB |= mask; break;
#endif
#if NIUS_HAS_PORT(0x04)
    case 2: if (mode == OUTPUT) TRISC &= (unsigned int)~mask; else TRISC |= mask; break;
#endif
#if NIUS_HAS_PORT(0x08)
    case 3: if (mode == OUTPUT) TRISD &= (unsigned int)~mask; else TRISD |= mask; break;
#endif
#if NIUS_HAS_PORT(0x10)
    case 4: if (mode == OUTPUT) TRISE &= (unsigned int)~mask; else TRISE |= mask; break;
#endif
#if NIUS_HAS_PORT(0x20)
    case 5: if (mode == OUTPUT) TRISF &= (unsigned int)~mask; else TRISF |= mask; break;
#endif
#if NIUS_HAS_PORT(0x40)
    case 6: if (mode == OUTPUT) TRISG &= (unsigned int)~mask; else TRISG |= mask; break;
#endif
    default: break;
    }
}

void digitalWrite(unsigned char pin, unsigned char value)
{
    unsigned int mask = (unsigned int)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
#if NIUS_HAS_PORT(0x01)
    case 0: if (value) LATA |= mask; else LATA &= (unsigned int)~mask; break;
#endif
#if NIUS_HAS_PORT(0x02)
    case 1: if (value) LATB |= mask; else LATB &= (unsigned int)~mask; break;
#endif
#if NIUS_HAS_PORT(0x04)
    case 2: if (value) LATC |= mask; else LATC &= (unsigned int)~mask; break;
#endif
#if NIUS_HAS_PORT(0x08)
    case 3: if (value) LATD |= mask; else LATD &= (unsigned int)~mask; break;
#endif
#if NIUS_HAS_PORT(0x10)
    case 4: if (value) LATE |= mask; else LATE &= (unsigned int)~mask; break;
#endif
#if NIUS_HAS_PORT(0x20)
    case 5: if (value) LATF |= mask; else LATF &= (unsigned int)~mask; break;
#endif
#if NIUS_HAS_PORT(0x40)
    case 6: if (value) LATG |= mask; else LATG &= (unsigned int)~mask; break;
#endif
    default: break;
    }
}

unsigned char digitalRead(unsigned char pin)
{
    unsigned int mask = (unsigned int)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
#if NIUS_HAS_PORT(0x01)
    case 0: return (unsigned char)((PORTA & mask) ? 1 : 0);
#endif
#if NIUS_HAS_PORT(0x02)
    case 1: return (unsigned char)((PORTB & mask) ? 1 : 0);
#endif
#if NIUS_HAS_PORT(0x04)
    case 2: return (unsigned char)((PORTC & mask) ? 1 : 0);
#endif
#if NIUS_HAS_PORT(0x08)
    case 3: return (unsigned char)((PORTD & mask) ? 1 : 0);
#endif
#if NIUS_HAS_PORT(0x10)
    case 4: return (unsigned char)((PORTE & mask) ? 1 : 0);
#endif
#if NIUS_HAS_PORT(0x20)
    case 5: return (unsigned char)((PORTF & mask) ? 1 : 0);
#endif
#if NIUS_HAS_PORT(0x40)
    case 6: return (unsigned char)((PORTG & mask) ? 1 : 0);
#endif
    default: return 0;
    }
}

void delayMicroseconds(unsigned int us)
{
    /* __delay_us needs a constant, so the wait is spent in fixed steps.
       The residue below ten microseconds is a handful of instructions,
       which is the resolution this API has on this part anyway. */
    while (us >= 10U) {
        __delay_us(10);
        us = (unsigned int)(us - 10U);
    }
}

void delay(unsigned int ms)
{
    while (ms--) {
        __delay_ms(1);
        g_ms++;
    }
}

unsigned long millis(void)
{
    return g_ms;
}

long map(long value, long from_low, long from_high, long to_low, long to_high)
{
    long span = from_high - from_low;

    if (span == 0)
        return to_low;
    return (value - from_low) * (to_high - to_low) / span + to_low;
}

void shiftOut(unsigned char data_pin, unsigned char clock_pin,
              unsigned char bit_order, unsigned char value)
{
    unsigned char i;

    for (i = 0; i < 8; i++) {
        unsigned char bit = (bit_order == LSBFIRST)
            ? (unsigned char)((value >> i) & 1)
            : (unsigned char)((value >> (7 - i)) & 1);

        digitalWrite(data_pin, bit);
        digitalWrite(clock_pin, HIGH);
        digitalWrite(clock_pin, LOW);
    }
}

unsigned char shiftIn(unsigned char data_pin, unsigned char clock_pin,
                      unsigned char bit_order)
{
    unsigned char value = 0;
    unsigned char i;

    for (i = 0; i < 8; i++) {
        digitalWrite(clock_pin, HIGH);
        if (digitalRead(data_pin)) {
            if (bit_order == LSBFIRST)
                value = (unsigned char)(value | (1u << i));
            else
                value = (unsigned char)(value | (1u << (7 - i)));
        }
        digitalWrite(clock_pin, LOW);
    }
    return value;
}

void randomSeed(unsigned long seed)
{
    if (seed != 0)
        g_seed = seed;
}

long random(long range)
{
    g_seed = g_seed * 1103515245UL + 12345UL;
    if (range <= 0)
        return 0;
    return (long)((g_seed >> 16) % (unsigned long)range);
}

long randomRange(long low, long high)
{
    if (high <= low)
        return low;
    return low + random(high - low);
}

int main(void)
{
    setup();
    for (;;)
        loop();
    return 0;
}
