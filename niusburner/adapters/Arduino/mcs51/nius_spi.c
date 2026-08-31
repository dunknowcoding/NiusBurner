/*
 * Software SPI master for classic 8051 parts. See nius_spi.h.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Mask-based port access: `P1 & mask` reads the pin, `P1 |= mask` reads the
 * latch. MISO is held released (written 1) so the pin can be read.
 */

#include "nius_spi.h"

#ifdef __SDCC
#include <8052.h>
#endif

#ifndef NIUS_SPI_SCK_BIT
#define NIUS_SPI_SCK_BIT 3
#endif
#ifndef NIUS_SPI_MOSI_BIT
#define NIUS_SPI_MOSI_BIT 4
#endif
#ifndef NIUS_SPI_MISO_BIT
#define NIUS_SPI_MISO_BIT 2
#endif

#define SCK_M  ((unsigned char)(1u << NIUS_SPI_SCK_BIT))
#define MOSI_M ((unsigned char)(1u << NIUS_SPI_MOSI_BIT))
#define MISO_M ((unsigned char)(1u << NIUS_SPI_MISO_BIT))

static unsigned char g_msb_first = NIUS_SPI_MSBFIRST;
static unsigned char g_cpol;
static unsigned char g_cpha;
static unsigned char g_extra;                 /* spins added per half clock */

/*
 * An exact number of machine cycles, and nothing else.
 *
 * This used to be `while (n--) { __asm nop... __endasm; }`: a hand-counted
 * body inside a loop whose own cost was whatever SDCC emitted that day. A
 * bit-banged bus is a timing contract, so the delay is assembly and the
 * count is arithmetic.
 *
 * The counter is read straight from the global and the register it uses is
 * saved, because SDCC's allocation is not part of the contract -- an
 * earlier attempt here assumed the local landed in DPL and it was actually
 * in r7, which would have looped an arbitrary number of times.
 *
 *   push ar7          2      mov r7,_g_extra   2
 *   mov  a,r7         1      jz  done          2
 *   loop: nop x6      6      djnz r7,loop      2
 *   pop  ar7          2
 *
 * so the delay is 15 + 8 * g_extra machine cycles, plus the call and
 * return the compiler adds. One machine cycle is 12 oscillator periods:
 * 1.085 us at 11.0592 MHz.
 */
#define NIUS_SPI_HALF_BASE_MC 15U
#define NIUS_SPI_HALF_STEP_MC 8U

static void half(void)
{
#ifdef __SDCC
    __asm
        nop
        nop
        nop
        nop
        nop
        nop
        push    ar7
        mov     r7,_g_extra
        mov     a,r7
        jz      00062$
    00061$:
        nop
        nop
        nop
        nop
        nop
        nop
        djnz    r7,00061$
    00062$:
        pop     ar7
    __endasm;
#endif
}

#ifdef __SDCC

/*
 * The port pins are bit-addressable, so each edge is one machine cycle.
 *
 * These were helper functions taking a level and branching on it, called
 * three times per bit. That made an SPI bit cost about 213 machine
 * cycles, of which the deliberate half-bit delay was 15 -- the
 * bus ran at the speed of the C, not the speed it was asked for. `setb` and
 * `clr` on a bit-addressable SFR are one cycle and two bytes, so this is
 * both faster and smaller.
 *
 * P1 is bit-addressable at 0x90, so bit n lives at 0x90 + n.
 */
__sbit __at (0x90 + NIUS_SPI_SCK_BIT)  NIUS_SCK;
__sbit __at (0x90 + NIUS_SPI_MOSI_BIT) NIUS_MOSI;
__sbit __at (0x90 + NIUS_SPI_MISO_BIT) NIUS_MISO;

#define sck_write(level)  do { if (level) NIUS_SCK = 1; else NIUS_SCK = 0; } while (0)
#define mosi_write(level) do { if (level) NIUS_MOSI = 1; else NIUS_MOSI = 0; } while (0)
#define miso_read()       ((unsigned char)NIUS_MISO)

#else

static void sck_write(unsigned char level) { (void)level; }
static void mosi_write(unsigned char level) { (void)level; }
static unsigned char miso_read(void) { return 0; }

#endif

void nius_spi_begin(void)
{
    g_msb_first = NIUS_SPI_MSBFIRST;
    g_cpol = 0;
    g_cpha = 0;
    g_extra = 0;
#ifdef __SDCC
    P1 |= MISO_M;                 /* released, so the pin can be read */
#endif
    sck_write(g_cpol);
    mosi_write(0);
}

void nius_spi_end(void)
{
    sck_write(g_cpol);
    mosi_write(0);
}

void nius_spi_set_bit_order(unsigned char msb_first)
{
    g_msb_first = (unsigned char)(msb_first ? 1 : 0);
}

void nius_spi_set_data_mode(unsigned char mode)
{
    /* SPI_MODEn are AVR SPCR bits: 0x08 is CPOL and 0x04 is CPHA. */
    g_cpol = (unsigned char)((mode & 0x08) ? 1 : 0);
    g_cpha = (unsigned char)((mode & 0x04) ? 1 : 0);
    sck_write(g_cpol);
}

void nius_spi_set_clock_divider(unsigned char divider)
{
    /*
     * There is no hardware prescaler to program, so the divider becomes idle
     * time inside the half-clock. The *ratios* between settings hold; the
     * absolute rate does not match an AVR at the same setting, and cannot.
     */
    switch (divider) {
    case SPI_CLOCK_DIV2:   g_extra = 0; break;
    case SPI_CLOCK_DIV4:   g_extra = 1; break;
    case SPI_CLOCK_DIV8:   g_extra = 3; break;
    case SPI_CLOCK_DIV16:  g_extra = 7; break;
    case SPI_CLOCK_DIV32:  g_extra = 15; break;
    case SPI_CLOCK_DIV64:  g_extra = 31; break;
    case SPI_CLOCK_DIV128: g_extra = 63; break;
    default:               g_extra = 1; break;
    }
}

unsigned char nius_spi_transfer(unsigned char value)
{
    unsigned char bit;
    unsigned char in = 0;
    unsigned char out;
    unsigned char idle = g_cpol;
    unsigned char active = (unsigned char)(g_cpol ? 0 : 1);
    /*
     * The mode flags are read from memory on each of the eight bits. Copying
     * them into locals first was tried and is worse on both counts: two more
     * live values push SDCC past what it can keep in registers, and the
     * measured bit period went from 190 us to 204 us while the code grew 23
     * bytes. Left as it is on the evidence.
     */
    for (bit = 0; bit < 8; bit++) {
        if (g_msb_first) {
            out = (unsigned char)((value & 0x80) ? 1 : 0);
            value = (unsigned char)(value << 1);
        } else {
            out = (unsigned char)(value & 1);
            value = (unsigned char)(value >> 1);
        }

        if (g_cpha) {
            /* CPHA = 1: data changes on the leading edge, sampled on the
               trailing one. */
            sck_write(active);
            mosi_write(out);
            half();
            sck_write(idle);
            half();
        } else {
            /* CPHA = 0: data is set up before the leading edge. */
            mosi_write(out);
            half();
            sck_write(active);
            half();
        }

        if (g_msb_first)
            in = (unsigned char)((in << 1) | miso_read());
        else
            in = (unsigned char)((in >> 1) | (unsigned char)(miso_read() << 7));

        if (!g_cpha) {
            sck_write(idle);
            half();
        }
    }
    return in;
}
