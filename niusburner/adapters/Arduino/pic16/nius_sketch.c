/*
 * The Arduino API on a mid-range PIC16.
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
 * Configuration word.
 *
 * A mid-range PIC latches its oscillator, watchdog and programming mode
 * from a word at 0x2007 rather than from anything the program does at run
 * time, and an image that leaves it out is programmed onto whatever the
 * erased part already holds -- all ones. That is the watchdog on, the
 * oscillator in RC mode and low-voltage programming enabled, so a sketch
 * built without this block resets roughly every 18 ms whatever clock is
 * fitted, and RB3 is not an I/O pin.
 *
 * WDTE off is the one that matters most: nothing in this runtime clears
 * the watchdog, because a sketch that wants one should ask for it.
 * LVP off gives RB3 back and matches how this toolchain programs the
 * part. The oscillator follows the clock the board declares, since XT
 * cannot start a 20 MHz crystal and HS is wasteful below 4 MHz.
 *
 * A sketch that needs its own settings defines NIUS_NO_CONFIG and supplies
 * a full set; two config blocks in one program is an error, not a merge.
 */
#ifndef NIUS_NO_CONFIG

/*
 * A part with no oscillator pins bonded out has to run from its internal
 * RC, and selecting a crystal mode on one leaves it with no clock at all.
 */
#ifndef NIUS_PIC_OSC_INTERNAL
#define NIUS_PIC_OSC_INTERNAL 0
#endif

#if NIUS_PIC_OSC_INTERNAL == 1
#pragma config FOSC = INTRCIO
#elif NIUS_PIC_OSC_INTERNAL == 2
/* Same oscillator, a later spelling of the same setting. */
#pragma config FOSC = INTOSCIO
#elif _XTAL_FREQ > 4000000UL
#pragma config FOSC = HS
#elif _XTAL_FREQ > 200000UL
#pragma config FOSC = XT
#else
#pragma config FOSC = LP
#endif

/*
 * Not every member of the family implements every bit. The 16F84A has no
 * brown-out, no low-voltage programming and no data protection; the
 * 16F62xA have no flash write protection. Naming a bit a part does not
 * have is an error rather than a no-op, so the catalog says which to
 * leave out.
 */
#ifndef NIUS_PIC_CFG_BOREN
#define NIUS_PIC_CFG_BOREN 1
#endif
#ifndef NIUS_PIC_CFG_LVP
#define NIUS_PIC_CFG_LVP 1
#endif
#ifndef NIUS_PIC_CFG_CPD
#define NIUS_PIC_CFG_CPD 1
#endif
#ifndef NIUS_PIC_CFG_WRT
#define NIUS_PIC_CFG_WRT 1
#endif

#pragma config WDTE = OFF
/*
 * The power-up timer holds the part in reset for 72 ms after VDD rises,
 * which is what a board with a slow supply wants. An in-circuit debugger
 * does not: MPLAB refuses to start a debug session while PWRTE is set,
 * because it cannot take control during that window. Building with
 * NIUS_PIC_CFG_PWRTE=0 turns it off for a debug image without editing the
 * sketch's own configuration.
 */
#ifndef NIUS_PIC_CFG_PWRTE
#define NIUS_PIC_CFG_PWRTE 1
#endif
#if NIUS_PIC_CFG_PWRTE
#pragma config PWRTE = ON
#else
#pragma config PWRTE = OFF
#endif
#pragma config CP = OFF

#if NIUS_PIC_CFG_BOREN
#pragma config BOREN = ON
#endif
#if NIUS_PIC_CFG_LVP
#pragma config LVP = OFF
#endif
#if NIUS_PIC_CFG_CPD
#pragma config CPD = OFF
#endif
#if NIUS_PIC_CFG_WRT
#pragma config WRT = OFF
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
 * The 8-pin parts do not call their single port A. It is GPIO, its
 * direction register is TRISIO, and the names PORTA and TRISA do not
 * exist for them at all -- so the port style is a switch rather than a
 * count of one.
 */
#ifndef NIUS_PIC_GPIO_STYLE
#define NIUS_PIC_GPIO_STYLE 0
#endif
#if NIUS_PIC_GPIO_STYLE
#define NIUS_PORT0  GPIO
#define NIUS_TRIS0  TRISIO
#else
#define NIUS_PORT0  PORTA
#define NIUS_TRIS0  TRISA
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
    case 0: if (mode == OUTPUT) NIUS_TRIS0 &= (unsigned char)~mask; else NIUS_TRIS0 |= mask; break;
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
    /*
     * The pull-ups are enabled for a whole port at once, by a bit that is
     * active low. Which port, and what the bit is called, follows the same
     * split as the port names: GPIO on the 8-pin parts, PORTB elsewhere.
     */
#if NIUS_PIC_GPIO_STYLE
    if (mode == INPUT_PULLUP && PORT_OF(pin) == 0)
        OPTION_REGbits.nGPPU = 0;
#else
    if (mode == INPUT_PULLUP && PORT_OF(pin) == 1)
        OPTION_REGbits.nRBPU = 0;
#endif
}

void digitalWrite(unsigned char pin, unsigned char value)
{
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
    case 0: if (value) NIUS_PORT0 |= mask; else NIUS_PORT0 &= (unsigned char)~mask; break;
#if NIUS_PIC_PORTS > 1
    case 1: if (value) PORTB |= mask; else PORTB &= (unsigned char)~mask; break;
#endif
#if NIUS_PIC_PORTS > 2
    case 2: if (value) PORTC |= mask; else PORTC &= (unsigned char)~mask; break;
#endif
#if NIUS_PIC_PORTS > 3
    case 3: if (value) PORTD |= mask; else PORTD &= (unsigned char)~mask; break;
#endif
#if NIUS_PIC_PORTS > 4
    case 4: if (value) PORTE |= mask; else PORTE &= (unsigned char)~mask; break;
#endif
    default: break;
    }
}

unsigned char digitalRead(unsigned char pin)
{
    unsigned char mask = (unsigned char)(1u << BIT_OF(pin));

    switch (PORT_OF(pin)) {
    case 0: return (unsigned char)((NIUS_PORT0 & mask) ? 1 : 0);
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

/*
 * What the `while (ms--)` loop in delay() costs per pass, in instruction
 * cycles. __delay_ms() is exact, so this is the whole of the remaining
 * error: the decrement, the test and the branch happen between one
 * millisecond and the next, and the built-in cannot know about them.
 *
 * Fitted on an 11.0592 MHz PIC16F877A: with no compensation, five seconds
 * of delay() measured 5.0242 s over eleven intervals, which is 4.24 us per
 * millisecond once the marker line's own transmission is taken out. One
 * instruction cycle is four oscillator periods, so that is close to twelve.
 *
 * Carried in cycles rather than microseconds because cycles are what does
 * not change with the crystal. Refit it if the body of delay() changes.
 */
#ifndef NIUS_PIC_DELAY_LOOP_CY
#define NIUS_PIC_DELAY_LOOP_CY 12UL
#endif

#define NIUS_PIC_DELAY_LOOP_US     ((NIUS_PIC_DELAY_LOOP_CY * 4UL * 1000000UL) / _XTAL_FREQ)

/*
 * A millisecond, less what the loop around it already spends. Below about
 * 1 MHz the loop costs more than the millisecond it is correcting, so the
 * correction is dropped rather than allowed to go negative.
 */
#if NIUS_PIC_DELAY_LOOP_US > 0 && NIUS_PIC_DELAY_LOOP_US < 500
#define __delay_ms_compensated() __delay_us(1000 - NIUS_PIC_DELAY_LOOP_US)
#else
#define __delay_ms_compensated() __delay_ms(1)
#endif

void delay(unsigned int ms)
{
    /*
     * The millisecond counter is advanced once, not once per iteration.
     * g_ms is 32-bit and this part has an 8-bit ALU, so incrementing it
     * inside the loop put a dozen-odd instructions between every
     * __delay_ms(1) -- time the built-in does not know about and cannot
     * subtract. Measured on an 11.0592 MHz PIC16F877A, delay(1000) ran
     * about 1.4 % long because of it.
     *
     * Nothing observes g_ms while delay() is running: there is no
     * interrupt in this runtime, so millis() can only be read before or
     * after, and both see the same value either way.
     */
    g_ms += ms;
    while (ms--)
        __delay_ms_compensated();
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
#if NIUS_PIC_ANALOG == 1
    ADCON1 = 0x06;              /* every PORTA/PORTE pin digital */
#elif NIUS_PIC_ANALOG == 2
    CMCON = 0x07;               /* comparators off, PORTA digital */
#elif NIUS_PIC_ANALOG == 3
    ANSEL = 0x00;               /* every analog select off */
#elif NIUS_PIC_ANALOG == 4
    ANSEL = 0x00;               /* the 8-pin parts have both */
    CMCON = 0x07;
#endif
    setup();
    for (;;)
        loop();
}
#endif
