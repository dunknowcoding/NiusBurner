/*
 * AT89S52 UART: 8N1 on P3.1/P3.0.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * 9600 uses Timer 1 mode 2 (TH1=0xFD at 11.0592 MHz, SMOD=0). That is the
 * textbook AT89S52 recipe. Timer 2 as baud generator was emitting at 2x
 * (Fosc/16 instead of the datasheet Fosc/32) and T2OE can steal P1.0.
 *
 * 115200 uses Timer 2 with RCAP2 = 65536 - Fosc/(32*baud) = 0xFFFD.
 */

#include "nius_serial.h"

#ifdef __SDCC
#include <8052.h>
/* Not in 8052.h. T2OE (bit 1) clocks P1.0; must stay 0 on a no-XRAM DIP-40. */
__sfr __at(0xC9) T2MOD;
#endif

#ifndef NIUS_FOSC
#define NIUS_FOSC 11059200UL
#endif

void nius_serial_begin(unsigned long baud)
{
#ifdef __SDCC
    P3 |= 0x02; /* quasi-bidirectional TXD must be written 1 */
    SCON = 0x50; /* mode 1, 8-bit UART, REN */
    ES = 0;
    RI = 0;
    T2MOD = 0x00;

    if (baud == 115200UL) {
        unsigned int reload = (unsigned int)(65536UL - (NIUS_FOSC / (32UL * 115200UL)));
        TR1 = 0;
        RCAP2H = (unsigned char)(reload >> 8);
        RCAP2L = (unsigned char)reload;
        TH2 = RCAP2H;
        TL2 = RCAP2L;
        T2CON = 0x34; /* RCLK + TCLK + TR2 */
    } else {
        /* Mode 1 SMOD=0: baud = Fosc / (384 * (256-TH1)). 9600 -> 0xFD. */
        T2CON = 0x00;
        PCON &= 0x7F;
        TMOD = (unsigned char)((TMOD & 0x0F) | 0x20);
        TH1 = (unsigned char)(256UL - (NIUS_FOSC / (384UL * 9600UL)));
        TL1 = TH1;
        TR1 = 1;
    }
    TI = 1;
#else
    (void)baud;
#endif
}

void nius_serial_end(void)
{
#ifdef __SDCC
    TR1 = 0;
    TR2 = 0;
    REN = 0;
#endif
}

void nius_serial_write(unsigned char c)
{
#ifdef __SDCC
    while (!TI)
        ;
    TI = 0;
    SBUF = c;
#else
    (void)c;
#endif
}

void nius_serial_flush(void)
{
#ifdef __SDCC
    while (!TI)
        ;
#endif
}

unsigned char nius_serial_available(void)
{
#ifdef __SDCC
    return RI ? 1 : 0;
#else
    return 0;
#endif
}

int nius_serial_read(void)
{
#ifdef __SDCC
    unsigned char c;
    if (!RI)
        return -1;
    c = SBUF;
    RI = 0;
    return c;
#else
    return -1;
#endif
}

void nius_serial_print_s(const char *s)
{
    if (!s)
        return;
    while (*s)
        nius_serial_write((unsigned char)*s++);
}

void nius_serial_println(void)
{
    nius_serial_write('\r');
    nius_serial_write('\n');
}

void nius_serial_println_s(const char *s)
{
    nius_serial_print_s(s);
    nius_serial_println();
}

/*
 * One digit generator for every width and sign. The 16-bit entry point is
 * kept because it is the cheap common case and because the bench monitor
 * calls it, but the digits themselves are produced once, here.
 */
static void put_digits(unsigned long u, unsigned char base)
{
    char buf[34];
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
