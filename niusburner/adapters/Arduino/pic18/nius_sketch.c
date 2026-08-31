/*
 * The Arduino API on a PIC18.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Timing comes from XC8's __delay_ms / __delay_us, which are compile-time
 * cycle counts rather than a calibrated busy-wait: the compiler knows
 * _XTAL_FREQ and emits exactly the loop it needs. That makes delay() as
 * accurate as the crystal, and it is why there is no fitted constant here
 * the way there is on a part whose compiler cannot do this.
 *
 * Those built-ins only accept a compile-time constant, so the millisecond
 * loop calls __delay_ms(1) repeatedly and the microsecond one steps in
 * tens. The residue below ten microseconds is a handful of instructions,
 * which is the resolution the API has on this part anyway.
 *
 * No timer is claimed. A sketch is free to use all three, and millis()
 * therefore advances inside delay() and nowhere else -- the same trade the
 * other families make, and documented in translation.md.
 */

#include "nius_sketch.h"

#ifndef _XTAL_FREQ
#define _XTAL_FREQ 20000000UL
#endif

/*
 * Configuration.
 *
 * A PIC18 latches its oscillator, watchdog and programming mode the same
 * way a PIC16 does, and an image that leaves the bits out is programmed
 * onto whatever the erased part holds -- watchdog on, low-voltage
 * programming enabled, and RB5 taken away from the sketch.
 *
 * The spelling is not consistent across the family, which is why this is a
 * numbered profile rather than one block: the 18F4550 line calls the
 * oscillator FOSC and the brown-out BOR, while the 18F4520 line calls them
 * OSC and BOREN. Naming a bit a part does not have is an error, so the
 * catalog picks the profile that matches.
 *
 * A sketch that needs its own settings defines NIUS_NO_CONFIG and supplies
 * a complete set.
 */
#ifndef NIUS_PIC18_CONFIG
#define NIUS_PIC18_CONFIG 1
#endif

#ifndef NIUS_NO_CONFIG

#if NIUS_PIC18_CONFIG == 1
/* 18F2550 / 18F4550: FOSC, BOR, and PORTB digital on reset via PBADEN. */
#pragma config FOSC = HS
#pragma config WDT = OFF
#pragma config LVP = OFF
#pragma config PWRT = ON
#pragma config BOR = OFF
#pragma config PBADEN = OFF
#pragma config MCLRE = ON
#elif NIUS_PIC18_CONFIG == 2
/* 18F2520 / 18F4520 / 18F2620 / 18F4620: OSC and BOREN. */
#pragma config OSC = HS
#pragma config WDT = OFF
#pragma config LVP = OFF
#pragma config PWRT = ON
#pragma config BOREN = OFF
#pragma config PBADEN = OFF
#pragma config MCLRE = ON
#elif NIUS_PIC18_CONFIG == 3
/* 18F252 / 18F452: the older set, with no PBADEN and no MCLRE. */
#pragma config OSC = HS
#pragma config WDT = OFF
#pragma config LVP = OFF
#pragma config PWRT = ON
#pragma config BOR = OFF
#endif

#endif /* NIUS_NO_CONFIG */

static unsigned long g_ms;
static unsigned long g_seed = 1;

/* PORTx and TRISx are not at consecutive addresses on a 16F877A, so the
   port is selected by a switch rather than by arithmetic on a base. */
#define PORT_OF(p) ((unsigned char)((p) >> 3))
#define BIT_OF(p)  ((unsigned char)((p) & 7))

/*
 * How many ports this part brings out. The 40-pin members of the family
 * have A..E; the 28-pin ones stop at C, and naming PORTD on those is a
 * compile error rather than a pin that quietly does nothing. The board
 * catalog supplies the count.
 */
#ifndef NIUS_PIC_PORTS
#define NIUS_PIC_PORTS 5
#endif

/*
 * Which register makes the analog-capable pins digital at start-up:
 * 1 ADCON1, 2 CMCON, 3 ANSEL, 0 for a part with no analog at all. Naming
 * the wrong one is a compile error, so the catalog picks.
 */
#ifndef NIUS_PIC_ANALOG
#define NIUS_PIC_ANALOG 1
#endif

void pinMode(unsigned char pin, unsigned char mode)
{
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));

    /*
     * TRIS is inverted from the name: clearing a bit drives the pin,
     * setting it releases the pin to be read. There is no separate
     * pull-up control per pin here -- PORTB has one enable for the whole
     * port -- so INPUT_PULLUP is INPUT plus that enable.
     */
    switch (PORT_OF(pin)) {
    case 0: if (mode == OUTPUT) TRISA &= (unsigned char)~mask; else TRISA |= mask; break;
#if NIUS_PIC_PORTS > 1
    case 1: if (mode == OUTPUT) TRISB &= (unsigned char)~mask; else TRISB |= mask; break;
#endif
#if NIUS_PIC_PORTS > 2
    case 2: if (mode == OUTPUT) TRISC &= (unsigned char)~mask; else TRISC |= mask; break;
#endif
#if NIUS_PIC_PORTS > 3
    case 3: if (mode == OUTPUT) TRISD &= (unsigned char)~mask; else TRISD |= mask; break;
#endif
#if NIUS_PIC_PORTS > 4
    case 4: if (mode == OUTPUT) TRISE &= (unsigned char)~mask; else TRISE |= mask; break;
#endif
    default: break;
    }
    if (mode == INPUT_PULLUP && PORT_OF(pin) == 1)
        INTCON2bits.RBPU = 0;   /* active low: 0 enables the PORTB pull-ups */
}

void digitalWrite(unsigned char pin, unsigned char value)
{
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
    case 0: if (value) LATA |= mask; else LATA &= (unsigned char)~mask; break;
#if NIUS_PIC_PORTS > 1
    case 1: if (value) LATB |= mask; else LATB &= (unsigned char)~mask; break;
#endif
#if NIUS_PIC_PORTS > 2
    case 2: if (value) LATC |= mask; else LATC &= (unsigned char)~mask; break;
#endif
#if NIUS_PIC_PORTS > 3
    case 3: if (value) LATD |= mask; else LATD &= (unsigned char)~mask; break;
#endif
#if NIUS_PIC_PORTS > 4
    case 4: if (value) LATE |= mask; else LATE &= (unsigned char)~mask; break;
#endif
    default: break;
    }
}

unsigned char digitalRead(unsigned char pin)
{
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
    case 0: return (unsigned char)((PORTA & mask) ? 1 : 0);
#if NIUS_PIC_PORTS > 1
    case 1: return (unsigned char)((PORTB & mask) ? 1 : 0);
#endif
#if NIUS_PIC_PORTS > 2
    case 2: return (unsigned char)((PORTC & mask) ? 1 : 0);
#endif
#if NIUS_PIC_PORTS > 3
    case 3: return (unsigned char)((PORTD & mask) ? 1 : 0);
#endif
#if NIUS_PIC_PORTS > 4
    case 4: return (unsigned char)((PORTE & mask) ? 1 : 0);
#endif
    default: return 0;
    }
}

void delayMicroseconds(unsigned int us)
{
    /* __delay_us needs a literal, so the variable part is stepped in tens
       and the remainder below that is left to the call overhead. */
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
        if (bit_order == MSBFIRST)
            digitalWrite(data_pin, (unsigned char)((value & 0x80) ? 1 : 0));
        else
            digitalWrite(data_pin, (unsigned char)(value & 1));
        value = (unsigned char)(bit_order == MSBFIRST ? value << 1 : value >> 1);
        digitalWrite(clock_pin, HIGH);
        digitalWrite(clock_pin, LOW);
    }
}

unsigned char shiftIn(unsigned char data_pin, unsigned char clock_pin,
                      unsigned char bit_order)
{
    unsigned char i;
    unsigned char value = 0;

    for (i = 0; i < 8; i++) {
        digitalWrite(clock_pin, HIGH);
        if (bit_order == MSBFIRST)
            value = (unsigned char)((value << 1) | digitalRead(data_pin));
        else
            value = (unsigned char)((value >> 1) |
                                    (unsigned char)(digitalRead(data_pin) << 7));
        digitalWrite(clock_pin, LOW);
    }
    return value;
}

void randomSeed(unsigned long seed)
{
    if (seed)
        g_seed = seed;
}

static unsigned long next_random(void)
{
    g_seed = g_seed * 1103515245UL + 12345UL;
    return (g_seed >> 16) & 0x7FFFUL;
}

long random(long range)
{
    if (range <= 0)
        return 0;
    return (long)(next_random() % (unsigned long)range);
}

long randomRange(long low, long high)
{
    if (high <= low)
        return low;
    return low + random(high - low);
}

#ifdef ND_NIUS_SKETCH_MAIN
void main(void)
{
    /*
     * PORTA and PORTE leave reset as analog inputs. Until ADCON1 says
     * otherwise, digitalRead on those ports returns zero no matter what is
     * on the pin -- a silent wrong answer, so it is settled here before
     * the sketch runs. A sketch that wants the converter sets ADCON1
     * itself in setup(), which runs after this.
     */
    ADCON1 = 0x0F;              /* every analog pin digital */
    setup();
    for (;;)
        loop();
}
#endif
