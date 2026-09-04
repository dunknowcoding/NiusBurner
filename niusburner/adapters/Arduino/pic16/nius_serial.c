/*
 * Serial on the PIC16 USART, polled.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * No interrupt is claimed, so a sketch keeps every vector for itself and
 * the timing of everything else is unaffected by characters arriving. The
 * cost is that a byte is lost if the sketch does not read it before the
 * next one lands; the hardware has a two-deep FIFO, which is what a 9600
 * baud console needs in practice.
 *
 * The baud divisor is computed with rounding rather than truncation, and
 * the high-speed generator is chosen when it fits, because the error is
 * what decides whether a link works: at 20 MHz and 9600 baud, truncating
 * gives 129 (-0.16 %) and the low-speed generator gives 32 (+1.36 %).
 */

#include "nius_sketch.h"
#include "nius_serial.h"

/* Which pins the USART appears on; see nius_serial_begin(). */
#ifndef NIUS_PIC_USART
#define NIUS_PIC_USART 1
#endif

#ifndef _XTAL_FREQ
#define _XTAL_FREQ 20000000UL
#endif

void nius_serial_begin(unsigned long baud)
{
    unsigned long divisor;

    if (baud == 0)
        baud = 9600;

    /* BRGH = 1: divisor = Fosc / (16 * baud) - 1, rounded. */
    divisor = ((_XTAL_FREQ + (8UL * baud)) / (16UL * baud));
    if (divisor > 0)
        divisor -= 1;

    if (divisor > 255UL) {
        /* Too slow for the high-speed generator; fall back and recompute. */
        divisor = ((_XTAL_FREQ + (32UL * baud)) / (64UL * baud));
        if (divisor > 0)
            divisor -= 1;
        TXSTAbits.BRGH = 0;
    } else {
        TXSTAbits.BRGH = 1;
    }
    if (divisor > 255UL)
        divisor = 255UL;
    SPBRG = (unsigned char)divisor;

    /*
     * The transmit pin has to be an output. This said the opposite -- that
     * the USART takes both pins over once SPEN is set, so both could be
     * left as inputs -- and on a PIC16F877A that is simply not true: the
     * port keeps the pin, the USART configures perfectly, and nothing ever
     * reaches the wire.
     *
     * It failed silently, which is why it survived. nius_serial_write()
     * spins on TRMT, and TRMT means "the shift register is empty" -- which
     * is exactly what it reads when nothing is ever shifted. So every write
     * returned at once, every println completed, the sketch ran on, and the
     * only symptom was a port that stayed quiet.
     *
     * Which pins these are depends on the package: RC6/RC7 on the 28- and
     * 40-pin parts, PORTB on the 18-pin ones, and naming a port the part
     * does not have is a compile error.
     */
#if NIUS_PIC_USART == 2
    TRISBbits.TRISB2 = 0;      /* TX: driven by the USART */
    TRISBbits.TRISB1 = 1;      /* RX: stays an input */
#elif NIUS_PIC_USART == 3
    TRISBbits.TRISB2 = 0;      /* TX */
    TRISBbits.TRISB5 = 1;      /* RX */
#else
    TRISCbits.TRISC6 = 0;      /* TX */
    TRISCbits.TRISC7 = 1;      /* RX */
#endif

    TXSTAbits.SYNC = 0;        /* asynchronous */
    RCSTAbits.SPEN = 1;        /* serial port on; it owns the pins now */
    TXSTAbits.TXEN = 1;
    RCSTAbits.CREN = 1;        /* continuous receive */
}

void nius_serial_end(void)
{
    TXSTAbits.TXEN = 0;
    RCSTAbits.CREN = 0;
    RCSTAbits.SPEN = 0;
}

void nius_serial_write(unsigned char value)
{
    while (!TXSTAbits.TRMT)
        ;
    TXREG = value;
}

void nius_serial_flush(void)
{
    while (!TXSTAbits.TRMT)
        ;
}

unsigned char nius_serial_available(void)
{
    /*
     * A framing or overrun error latches the receiver until CREN is
     * toggled. Clearing it here means a burst of noise costs a character
     * rather than the rest of the session.
     */
    if (RCSTAbits.OERR) {
        RCSTAbits.CREN = 0;
        RCSTAbits.CREN = 1;
    }
    if (RCSTAbits.FERR)
        (void)RCREG;
    return (unsigned char)(PIR1bits.RCIF ? 1 : 0);
}

int nius_serial_read(void)
{
    if (!nius_serial_available())
        return -1;
    return (int)RCREG;
}

void nius_serial_println(void)
{
    nius_serial_write('\r');
    nius_serial_write('\n');
}

void nius_serial_print_s(const char *s)
{
    if (!s)
        return;
    while (*s)
        nius_serial_write((unsigned char)*s++);
}

void nius_serial_println_s(const char *s)
{
    nius_serial_print_s(s);
    nius_serial_println();
}

/* One digit generator for every width and sign. */
static void put_digits(unsigned long u, unsigned char base)
{
    /* 32 is the worst case exactly: a 32-bit value in base 2. */
    char buf[32];
    unsigned char n = 0;

    if (u == 0) {
        nius_serial_write('0');
        return;
    }
    while (u && n < sizeof buf) {
        unsigned char d = (unsigned char)(u % base);
        buf[n++] = (char)(d < 10 ? '0' + d : 'A' + (d - 10));
        u /= base;
    }
    while (n)
        nius_serial_write((unsigned char)buf[--n]);
}

void nius_serial_print_ulong(unsigned long value, unsigned char base)
{
    if (base < 2)
        base = 10;
    put_digits(value, base);
}

void nius_serial_print_long(long value, unsigned char base)
{
    if (base < 2)
        base = 10;
    /* Only base 10 carries a sign, the same as Arduino: print(-1, HEX)
       shows the two's-complement pattern, not "-1". */
    if (value < 0 && base == 10) {
        nius_serial_write('-');
        put_digits((unsigned long)(-value), base);
        return;
    }
    put_digits((unsigned long)value, base);
}

void nius_serial_print_int(int value, unsigned char base)
{
    nius_serial_print_long((long)value, base);
}

void nius_serial_println_int(int value, unsigned char base)
{
    nius_serial_print_long((long)value, base);
    nius_serial_println();
}

void nius_serial_println_long(long value, unsigned char base)
{
    nius_serial_print_long(value, base);
    nius_serial_println();
}

void nius_serial_println_ulong(unsigned long value, unsigned char base)
{
    nius_serial_print_ulong(value, base);
    nius_serial_println();
}
