/*
 * UART1 on a dsPIC30F: 8N1, polled.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * The pins are fixed on this family, which is why it is the one supported
 * here: every later 16-bit PIC routes its UART through Peripheral Pin
 * Select, and the physical pin then becomes a property of the board rather
 * than of the part. A runtime cannot guess that, so those parts declare no
 * UART and Serial is refused at translation time with a reason.
 *
 * The divisor is BRG = FCY / (16 * baud) - 1 in the default mode. Only an
 * exact result is accepted: the nearest divisor would transmit at a rate
 * nobody asked for, and there is no way to report that over the port being
 * configured. nius_serial_ok carries the answer instead.
 */

#include "nius_serial.h"

#include <xc.h>

#ifndef NIUS_FOSC
#define NIUS_FOSC 7372800UL
#endif
#ifndef FCY
#define FCY (NIUS_FOSC / 4UL)
#endif

/* 0 after begin() when this part and clock cannot produce that rate. */
unsigned char nius_serial_ok = 1;

void nius_serial_begin(unsigned long baud)
{
    unsigned long denominator = 16UL * baud;
    unsigned long divisor;

    nius_serial_ok = 1;
    if (baud == 0UL) {
        nius_serial_ok = 0;
        return;
    }

    divisor = FCY / denominator;
    if (divisor == 0UL || divisor > 65536UL || divisor * denominator != FCY) {
        nius_serial_ok = 0;
        return;
    }

    U1BRG = (unsigned int)(divisor - 1UL);
    U1MODE = 0x8000;            /* UARTEN, 8N1, no autobaud */
    U1STA = 0x0400;             /* UTXEN */
}

void nius_serial_end(void)
{
    U1STA &= (unsigned int)~0x0400;
    U1MODE = 0x0000;
}

void nius_serial_write(unsigned char value)
{
    while (U1STAbits.UTXBF)
        ;
    U1TXREG = value;
}

void nius_serial_flush(void)
{
    while (!U1STAbits.TRMT)
        ;
}

unsigned char nius_serial_available(void)
{
    return (unsigned char)(U1STAbits.URXDA ? 1 : 0);
}

int nius_serial_read(void)
{
    if (U1STAbits.OERR)
        U1STAbits.OERR = 0;     /* overrun latches the receiver off */
    if (!U1STAbits.URXDA)
        return -1;
    return (int)(U1RXREG & 0xFF);
}


/* Everything below is arithmetic and formatting: it touches no register
   and is identical on every family. */

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
