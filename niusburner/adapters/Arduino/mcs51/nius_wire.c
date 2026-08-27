/*
 * Software I2C master for classic 8051 parts. See nius_wire.h.
 *
 * Copyright 2026 dunknowcoding (NiusRobotLab)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Port access is deliberately mask-based rather than __sbit, because the
 * pins are configurable. That is also correct 8051: `P1 & mask` in an
 * expression compiles to MOV A,P1 and reads the *pin*, while `P1 |= mask`
 * compiles to ORL P1,#mask and reads the *latch*. Releasing a line is
 * writing 1 to it -- a quasi-bidirectional pin then floats to the bus
 * pull-up, which is what makes open-drain signalling possible at all.
 *
 * I2C specifies minimum times, not exact ones, so a bit-banged master is
 * allowed to be slow. Everything here errs slow.
 */

#include "nius_wire.h"

#ifdef __SDCC
#include <8052.h>
#endif

#ifndef NIUS_I2C_SCL_BIT
#define NIUS_I2C_SCL_BIT 0
#endif
#ifndef NIUS_I2C_SDA_BIT
#define NIUS_I2C_SDA_BIT 1
#endif

#define SCL_M ((unsigned char)(1u << NIUS_I2C_SCL_BIT))
#define SDA_M ((unsigned char)(1u << NIUS_I2C_SDA_BIT))

/* Bounded clock-stretch wait. A slave that never lets go is a bus fault, not
   something to hang the sketch on. */
#define STRETCH_LIMIT 200

static unsigned char g_extra;                 /* spins added per half bit */
static unsigned char g_rx[NIUS_WIRE_RX];
static unsigned char g_rx_len;
static unsigned char g_rx_pos;
static unsigned char g_addr;
static unsigned char g_status;

static void half(void)
{
#ifdef __SDCC
    unsigned char n = g_extra;

    __asm
        nop
        nop
        nop
        nop
    __endasm;
    while (n--) {
        __asm
            nop
            nop
            nop
            nop
            nop
            nop
            nop
            nop
        __endasm;
    }
#endif
}

#ifdef __SDCC

static void sda_release(void)
{
    P1 |= SDA_M;
}

static void sda_pull(void)
{
    P1 &= (unsigned char)~SDA_M;
}

static void scl_pull(void)
{
    P1 &= (unsigned char)~SCL_M;
}

static void scl_release(void)
{
    unsigned char guard = STRETCH_LIMIT;

    P1 |= SCL_M;
    while (!(P1 & SCL_M) && guard--)
        half();
}

static unsigned char sda_read(void)
{
    P1 |= SDA_M;
    return (unsigned char)((P1 & SDA_M) ? 1 : 0);
}

static void bus_start(void)
{
    sda_release();
    scl_release();
    half();
    sda_pull();
    half();
    scl_pull();
    half();
}

static void bus_stop(void)
{
    sda_pull();
    half();
    scl_release();
    half();
    sda_release();
    half();
}

/* Returns 1 when the slave pulled SDA low for the ACK bit. */
static unsigned char bus_write(unsigned char value)
{
    unsigned char bit;
    unsigned char ack;

    for (bit = 0; bit < 8; bit++) {
        if (value & 0x80)
            sda_release();
        else
            sda_pull();
        value = (unsigned char)(value << 1);
        half();
        scl_release();
        half();
        scl_pull();
        half();
    }
    sda_release();
    half();
    scl_release();
    half();
    ack = (unsigned char)(sda_read() ? 0 : 1);
    scl_pull();
    half();
    return ack;
}

static unsigned char bus_read(unsigned char ack)
{
    unsigned char bit;
    unsigned char value = 0;

    sda_release();
    for (bit = 0; bit < 8; bit++) {
        value = (unsigned char)(value << 1);
        half();
        scl_release();
        half();
        if (sda_read())
            value |= 1;
        scl_pull();
        half();
    }
    if (ack)
        sda_pull();
    else
        sda_release();
    half();
    scl_release();
    half();
    scl_pull();
    sda_release();
    half();
    return value;
}

#else  /* host build: the API exists so tests can link, the bus does not */

static void bus_start(void) { }
static void bus_stop(void) { }
static unsigned char bus_write(unsigned char value) { (void)value; return 0; }
static unsigned char bus_read(unsigned char ack) { (void)ack; return 0xFF; }

#endif

void nius_wire_begin(void)
{
    g_extra = 0;
    g_rx_len = 0;
    g_rx_pos = 0;
    g_status = NIUS_WIRE_OK;
#ifdef __SDCC
    P1 |= (unsigned char)(SCL_M | SDA_M);   /* both released */
#endif
}

void nius_wire_set_clock(unsigned long hz)
{
    /*
     * Coarse on purpose. A bit-banged master cannot hit an arbitrary rate,
     * and rounding *down* is the safe direction on I2C, so each band is the
     * fastest setting that is still at or below the request.
     */
    if (hz >= 100000UL)
        g_extra = 0;
    else if (hz >= 50000UL)
        g_extra = 1;
    else if (hz >= 25000UL)
        g_extra = 3;
    else
        g_extra = 7;
}

void nius_wire_begin_transmission(unsigned char addr7)
{
    g_addr = addr7;
    g_status = NIUS_WIRE_OK;
    bus_start();
    if (!bus_write((unsigned char)(addr7 << 1)))
        g_status = NIUS_WIRE_ADDR_NACK;
}

unsigned char nius_wire_write(unsigned char value)
{
    if (g_status != NIUS_WIRE_OK)
        return 0;
    if (!bus_write(value)) {
        g_status = NIUS_WIRE_DATA_NACK;
        return 0;
    }
    return 1;
}

unsigned char nius_wire_end_transmission(void)
{
    bus_stop();
    return g_status;
}

unsigned char nius_wire_request_from(unsigned char addr7, unsigned char count)
{
    unsigned char i;

    if (count > NIUS_WIRE_RX)
        count = NIUS_WIRE_RX;
    g_rx_len = 0;
    g_rx_pos = 0;
    bus_start();
    if (!bus_write((unsigned char)((addr7 << 1) | 1))) {
        bus_stop();
        g_status = NIUS_WIRE_ADDR_NACK;
        return 0;
    }
    for (i = 0; i < count; i++)
        g_rx[i] = bus_read((unsigned char)(i + 1 < count));
    bus_stop();
    g_rx_len = count;
    g_status = NIUS_WIRE_OK;
    return count;
}

unsigned char nius_wire_available(void)
{
    return (unsigned char)(g_rx_len - g_rx_pos);
}

int nius_wire_read(void)
{
    if (g_rx_pos >= g_rx_len)
        return -1;
    return (int)g_rx[g_rx_pos++];
}
