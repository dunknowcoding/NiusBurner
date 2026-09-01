/*
 * AT89S52 UART: 8N1 on P3.1/P3.0.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Timer 1 in mode 2 is the textbook generator: baud = Fosc / (384 * (256 -
 * TH1)), and SMOD in PCON doubles that. Between them they cover everything
 * up to 57600 at 11.0592 MHz. 115200 needs a finer divider than an 8-bit
 * reload can express, which is what Timer 2 is for: RCAP2 = 65536 -
 * Fosc / (32 * baud).
 *
 * Not every 8051 has a Timer 2 -- the 4 KB and 20-pin parts do not -- so
 * that branch is compiled in only where it exists, and a rate that needs it
 * is reported as unreachable rather than quietly set to something else.
 *
 * A reload is only accepted if the rate it actually produces is within 2 %
 * of the one asked for. Picking the nearest reload without checking is how
 * a request for 19200 ends up transmitting at 28800.
 *
 * T2OE (T2MOD bit 1) clocks P1.0 and must stay 0 on a no-XRAM DIP-40.
 */

#include "nius_serial.h"

#ifdef NIUS_ISP_ENTRY
/* Set by the bootloader-entry ISR when a byte finishes going out. */
extern volatile unsigned char nius_tx_done;
void nius_isp_entry_begin(void);
#endif

/* Whether this part has a Timer 2 to use as a baud generator. */
#ifndef NIUS_HAS_TIMER2
#define NIUS_HAS_TIMER2 1
#endif

/* Whether UART1's clock source is selected in AUXR (the 1T generations). */
#ifndef NIUS_UART_AUXR
#define NIUS_UART_AUXR 0
#endif

#ifdef __SDCC
#include <8052.h>
#if NIUS_HAS_TIMER2
/* Not in 8052.h. T2OE (bit 1) clocks P1.0; must stay 0 on a no-XRAM DIP-40. */
__sfr __at(0xC9) T2MOD;
#endif
#if NIUS_UART_AUXR
/*
 * The 1T generations put a UART1 clock select in AUXR, and it does not
 * come up on the setting the classic part has. S1ST2 (bit 0) reads 1 out
 * of reset, which points UART1 at Timer 2 -- so a Timer 1 reload written
 * on one of these parts is loaded correctly and then simply not used, and
 * the port transmits at whatever Timer 2 happens to be doing. T1x12 (bit
 * 6) reads 0, which is the 12-clock Timer 1 the divisors below assume;
 * it is cleared here as well so the rate does not depend on a reset value.
 */
__sfr __at(0x8E) AUXR;
#endif
#endif

#ifndef NIUS_FOSC
#define NIUS_FOSC 11059200UL
#endif

/*
 * Timer 1 mode 2 divides Fosc by 384 (SMOD=0) or 192 (SMOD=1) and then by
 * the reload. Folding the first division into a constant leaves a 16-bit
 * divide at run time instead of a 32-bit one: this core has neither
 * instruction, and SDCC's 32-bit routine costs about a thousand machine
 * cycles and several hundred bytes.
 */
#define NIUS_T1_BASE0 ((unsigned int)(NIUS_FOSC / 384UL))
#define NIUS_T1_BASE1 ((unsigned int)(NIUS_FOSC / 192UL))
/* Timer 2 reload for a rate Timer 1 cannot reach. */
#define NIUS_T2_RC(b) ((unsigned int)(65536UL - (NIUS_FOSC / (32UL * (b)))))

/*
 * Set to 0 by nius_serial_begin() when the requested rate cannot be
 * produced on this part. A sketch cannot be told over a UART that its UART
 * is misconfigured, so the flag is the only honest report available.
 */
unsigned char nius_serial_ok = 1;

void nius_serial_begin(unsigned long baud)
{
#ifdef __SDCC
    P3 |= 0x02; /* quasi-bidirectional TXD must be written 1 */
    SCON = 0x50; /* mode 1, 8-bit UART, REN */
    ES = 0;
    RI = 0;
#if NIUS_HAS_TIMER2
    T2MOD = 0x00;
#endif

    {
        unsigned int want = (unsigned int)baud;
        unsigned int reload = 0;
        unsigned char smod = 0;
        unsigned char placed = 0;

        nius_serial_ok = 1;

        /*
         * Only an exact division is accepted. Taking the nearest reload
         * without checking is how a request for 38400 at 11.0592 MHz ends
         * up transmitting at 28800: the rate is simply not available from
         * an 8-bit reload, and saying so beats sending at the wrong speed.
         */
        if (baud != 0UL && baud <= 65535UL) {
            reload = NIUS_T1_BASE0 / want;
            if (reload >= 1U && reload <= 256U
                && (unsigned long)reload * want == (unsigned long)NIUS_T1_BASE0) {
                placed = 1;
            } else {
                reload = NIUS_T1_BASE1 / want;
                if (reload >= 1U && reload <= 256U
                    && (unsigned long)reload * want
                       == (unsigned long)NIUS_T1_BASE1) {
                    smod = 1;
                    placed = 1;
                }
            }
        }

        if (placed) {
#if NIUS_HAS_TIMER2
            T2CON = 0x00;
#endif
#if NIUS_UART_AUXR
            AUXR &= (unsigned char)~0x41; /* UART1 from Timer 1, 12 clocks */
#endif
            if (smod)
                PCON |= 0x80;
            else
                PCON &= 0x7F;
            TMOD = (unsigned char)((TMOD & 0x0F) | 0x20);
            TH1 = (unsigned char)(256U - reload);
            TL1 = TH1;
            TR1 = 1;
        }
#if NIUS_HAS_TIMER2
        /*
         * The rates an 8-bit reload cannot express. Both constants fold at
         * compile time, so this costs a comparison rather than the 32-bit
         * division a general form would need.
         */
        else if (baud == 115200UL || baud == 38400UL) {
            unsigned int rc = (baud == 115200UL)
                ? NIUS_T2_RC(115200UL) : NIUS_T2_RC(38400UL);

            TR1 = 0;
            PCON &= 0x7F;
            RCAP2H = (unsigned char)(rc >> 8);
            RCAP2L = (unsigned char)rc;
            TH2 = RCAP2H;
            TL2 = RCAP2L;
            T2CON = 0x34;   /* RCLK + TCLK + TR2 */
            placed = 1;
        }
#endif
        if (!placed)
            nius_serial_ok = 0;
    }
    TI = 1;
#ifdef NIUS_ISP_ENTRY
    /* Arm the bootloader-entry watcher once the UART is up. */
    nius_isp_entry_begin();
#endif
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
#ifdef NIUS_ISP_ENTRY
    /*
     * With the bootloader-entry interrupt installed, TI is cleared by the
     * ISR before this could ever see it. The ISR records the event instead
     * and this waits on the record; polling TI here would hang forever.
     */
    while (!nius_tx_done)
        ;
    nius_tx_done = 0;
    SBUF = c;
#else
    while (!TI)
        ;
    TI = 0;
    SBUF = c;
#endif
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
 * kept because it is the cheap common case, but the digits themselves are
 * produced once, here.
 */
static void put_digits(unsigned long u, unsigned char base)
{
    /* 32 is the worst case exactly: a 32-bit value in base 2.
       These are statically allocated on this part, so the
       difference is internal RAM a sketch could have used. */
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
